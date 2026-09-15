import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../core/bitchat/bitchat_crypto.dart';
import '../../core/bitchat/bitchat_mesh.dart';
import '../../core/bitchat/bitchat_vault.dart';
import '../../core/network/gig_realtime.dart';
import '../../data/models/models.dart';
import '../../data/repositories/karma_repository.dart';

/// Coordinates the three independent Bitchat boundaries: cryptography, server relay and BLE.
class BitchatController extends ChangeNotifier {
  BitchatController({
    required this.repository,
    required this.user,
    required this.gig,
    BitchatCrypto? crypto,
    BitchatVault? vault,
    BitchatMesh? mesh,
  })  : _crypto = crypto ?? BitchatCrypto(userId: user.id),
        _vault = vault ?? BitchatVault(userId: user.id),
        _mesh = mesh ?? BitchatMesh();

  final KarmaRepository repository;
  final User user;
  final Gig gig;
  final BitchatCrypto _crypto;
  final BitchatVault _vault;
  final BitchatMesh _mesh;

  final List<BitchatMessage> _messages = <BitchatMessage>[];
  final Set<String> _openingEnvelopes = <String>{};
  StreamSubscription<BitchatEnvelope>? _meshMessages;
  StreamSubscription<BitchatMeshState>? _meshStates;
  StreamSubscription<int>? _meshPeers;
  GigRealtimeConnection? _realtime;
  Timer? _burnTimer;

  BitchatSession? _session;
  BitchatMode _mode = BitchatMode.hybrid;
  BitchatMeshState _meshState = BitchatMeshState.idle;
  LiveConnectionState _serverState = LiveConnectionState.paused;
  int _ttlSeconds = 3600;
  int _peerCount = 0;
  bool _loading = true;
  bool _sending = false;
  bool _prefetching = false;
  bool _wiped = false;
  bool _wipeComplete = false;
  Object? _error;
  bool _disposed = false;

  List<BitchatMessage> get messages => List<BitchatMessage>.unmodifiable(_messages);
  BitchatSession? get session => _session;
  BitchatMode get mode => _mode;
  BitchatMeshState get meshState => _meshState;
  LiveConnectionState get serverState => _serverState;
  int get ttlSeconds => _ttlSeconds;
  int get peerCount => _peerCount;
  bool get loading => _loading;
  bool get sending => _sending;
  bool get wiped => _wiped;
  bool get wipeComplete => _wipeComplete;
  Object? get error => _error;
  bool get canSend => !_wiped && (_session?.canSend ?? false);
  String get deviceId => _crypto.deviceId;

  Future<void> initialize() async {
    _loading = true;
    _error = null;
    _notify();
    try {
      _messages
        ..clear()
        ..addAll(await _vault.load(gig.id));
      _mode = await _vault.loadMode();
      _ttlSeconds = await _vault.loadTtl();
      await _crypto.initialize();

      BitchatSession? active;
      try {
        await repository.registerBitchatDevice(
          await _crypto.registrationPayload(),
        );
        active = await repository.bitchatSession(gig.id);
        await _crypto.cacheSession(active);
      } on Object catch (error) {
        active = await _crypto.cachedSession(gig.id);
        if (active == null) rethrow;
        _error = error;
      }
      if (_disposed || _wiped) return;
      _session = active;
      if (!active.ttlOptions.contains(_ttlSeconds)) {
        _ttlSeconds = active.ttlOptions.contains(3600)
            ? 3600
            : active.ttlOptions.firstOrNull ?? 3600;
      }

      _meshMessages = _mesh.envelopes.listen(_acceptEnvelope);
      _meshStates = _mesh.states.listen((BitchatMeshState value) {
        _meshState = value;
        _notify();
      });
      _meshPeers = _mesh.peerCounts.listen((int value) {
        _peerCount = value;
        _notify();
      });
      if (_mode != BitchatMode.server) await _mesh.start();
      _openRealtime();
      await refreshInbox(silent: true);
      unawaited(_prefetchClaims());
      _burnTimer = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
    } on Object catch (error) {
      _error = error;
    } finally {
      _loading = false;
      _notify();
    }
  }

  Future<void> refreshInbox({bool silent = false}) async {
    final BitchatSession? active = _session;
    if (active == null || _wiped) return;
    if (!silent) {
      _error = null;
      _notify();
    }
    try {
      final List<BitchatEnvelope> envelopes = await repository.bitchatInbox(
        gigId: gig.id,
        deviceId: deviceId,
      );
      for (final BitchatEnvelope envelope in envelopes) {
        await _acceptEnvelope(envelope);
      }
      await _syncOwnKeys();
    } on Object catch (error) {
      if (!silent) _error = error;
    } finally {
      _notify();
    }
  }

  Future<void> send(String raw) async {
    final String text = raw.trim();
    final BitchatSession? active = _session;
    if (_sending || !canSend || active == null || text.isEmpty) return;
    if (text.length > 1500) {
      _error = ArgumentError('Messages can contain at most 1500 characters');
      _notify();
      return;
    }
    if (active.peerDevices.isEmpty) {
      _error = StateError('Your peer needs to open secure chat once to publish a key');
      _notify();
      return;
    }

    _sending = true;
    _error = null;
    final String messageId = _crypto.newMessageId();
    final DateTime sentAt = DateTime.now().toUtc();
    final BitchatMessage local = BitchatMessage(
      id: messageId,
      text: text,
      sentAt: sentAt,
      expiresAt: sentAt.add(Duration(seconds: _ttlSeconds)),
      isMine: true,
      delivery: BitchatDelivery.sending,
    );
    _messages.add(local);
    await _vault.save(gig.id, _messages);
    _notify();

    bool serverDelivered = false;
    bool meshQueued = false;
    int acceptedFor = 0;
    Object? firstFailure;
    try {
      for (final BitchatDevice peer in active.peerDevices) {
        try {
          BitchatClaimedPreKey? claimed = await _crypto.takeCachedClaim(
            gig.id,
            peer.deviceId,
          );
          claimed ??= await repository.claimBitchatPreKey(
            gigId: gig.id,
            senderDeviceId: deviceId,
            recipientDeviceId: peer.deviceId,
          );
          if (_wiped) throw StateError('Conversation was erased');
          final BitchatEnvelope envelope = await _crypto.encrypt(
            messageId: messageId,
            gigId: gig.id,
            roomId: active.roomId,
            claimed: claimed,
            plaintext: text,
            ttlSeconds: _ttlSeconds,
            maxHops: 3,
            mode: _mode,
          );
          if (_wiped) throw StateError('Conversation was erased');
          bool accepted = false;
          if (_mode != BitchatMode.server) {
            final bool queued = await _mesh.publish(envelope);
            meshQueued = meshQueued || queued;
            accepted = accepted || queued;
          }
          if (_mode != BitchatMode.mesh) {
            try {
              await repository.sendBitchatEnvelope(gig.id, envelope);
              serverDelivered = true;
              accepted = true;
            } on Object catch (error) {
              firstFailure ??= error;
            }
          }
          if (accepted) acceptedFor += 1;
        } on Object catch (error) {
          // One stale device must not prevent delivery to the peer's other devices.
          firstFailure ??= error;
        }
      }
      if (acceptedFor == 0) {
        throw firstFailure ?? StateError('No secure transport accepted this message');
      }
      final BitchatDelivery delivery = serverDelivered && meshQueued
          ? BitchatDelivery.hybrid
          : serverDelivered
              ? BitchatDelivery.server
              : BitchatDelivery.mesh;
      _replaceMessage(messageId, delivery);
      if (firstFailure != null) _error = firstFailure;
      if (acceptedFor < active.peerDevices.length) {
        _error = StateError(
          'Delivered to $acceptedFor of ${active.peerDevices.length} peer devices; another device needs fresh keys.',
        );
      }
      unawaited(_prefetchClaims());
    } on Object catch (error) {
      _error = error;
      _replaceMessage(messageId, BitchatDelivery.failed);
    } finally {
      _sending = false;
      await _vault.save(gig.id, _messages);
      _notify();
    }
  }

  Future<void> setMode(BitchatMode value) async {
    if (_mode == value) return;
    _mode = value;
    await _vault.saveMode(value);
    if (value == BitchatMode.server) {
      await _mesh.stop();
    } else {
      await _mesh.start();
    }
    _notify();
  }

  Future<void> setTtl(int value) async {
    if (!(_session?.ttlOptions.contains(value) ?? false)) return;
    _ttlSeconds = value;
    await _vault.saveTtl(value);
    _notify();
  }

  /// Returns whether the safety server acknowledged the panic.
  Future<bool> panicAndWipe() async {
    if (_wiped) return true;
    final String currentDevice = deviceId;
    final Future<bool> serverAcknowledgement = repository
        .panicAndWipeBitchat(gigId: gig.id, deviceId: currentDevice)
        .then<bool>((_) => true, onError: (Object error, StackTrace _) {
      _error = error;
      return false;
    });

    // Destruction never waits for the network. Disable the screen first, then erase all
    // transcript vaults, identity/prekey/session material and queued BLE ciphertext.
    _wiped = true;
    _messages.clear();
    _openingEnvelopes.clear();
    _burnTimer?.cancel();
    _notify();
    try {
      await Future.wait<void>(<Future<void>>[
        _realtime?.close() ?? Future<void>.value(),
        _meshMessages?.cancel() ?? Future<void>.value(),
        _meshStates?.cancel() ?? Future<void>.value(),
        _meshPeers?.cancel() ?? Future<void>.value(),
        _mesh.emergencyWipe(),
        _vault.emergencyWipe(),
        _crypto.emergencyWipe(),
      ]);
      _wipeComplete = true;
    } on Object catch (error) {
      // Future.wait starts every erasure before reporting one failure. Keep the screen
      // disabled and surface the storage failure rather than pretending it did not occur.
      _error = error;
      _notify();
    }
    return serverAcknowledgement.timeout(
      const Duration(seconds: 4),
      onTimeout: () => false,
    );
  }

  Future<void> _acceptEnvelope(BitchatEnvelope envelope) async {
    final BitchatSession? active = _session;
    if (_wiped ||
        active == null ||
        envelope.gigId != gig.id ||
        envelope.roomId != active.roomId ||
        envelope.recipientDeviceId != deviceId ||
        envelope.isExpired ||
        _openingEnvelopes.contains(envelope.messageId) ||
        _messages.any((BitchatMessage item) => item.id == envelope.messageId)) {
      return;
    }
    final BitchatDevice? peer = active.peerDevices
        .where((BitchatDevice item) => item.deviceId == envelope.senderDeviceId)
        .firstOrNull;
    if (peer == null || peer.identityKey != envelope.senderIdentityKey) return;
    _openingEnvelopes.add(envelope.messageId);
    try {
      final String text = await _crypto.decrypt(
        envelope,
        expectedIdentityKey: peer.identityKey,
      );
      if (_wiped) return;
      _messages.add(
        BitchatMessage(
          id: envelope.messageId,
          text: text,
          sentAt: envelope.sentAt,
          expiresAt: envelope.expiresAt,
          isMine: false,
          delivery: envelope.transport == 'mesh'
              ? BitchatDelivery.mesh
              : BitchatDelivery.server,
        ),
      );
      _messages.sort(
        (BitchatMessage a, BitchatMessage b) => a.sentAt.compareTo(b.sentAt),
      );
      await _vault.save(gig.id, _messages);
      _notify();
    } on Object catch (error) {
      // Authentication failures are never rendered as messages. Keep the first error
      // visible so corruption or an identity change is not silently normalized.
      _error ??= error;
      _notify();
    } finally {
      _openingEnvelopes.remove(envelope.messageId);
    }
  }

  Future<void> _prefetchClaims() async {
    final BitchatSession? active = _session;
    if (_prefetching ||
        _wiped ||
        active == null ||
        !active.canSend ||
        active.peerDevices.isEmpty) {
      return;
    }
    _prefetching = true;
    try {
      final List<BitchatClaimedPreKey> cached = await _crypto.cachedClaims(gig.id);
      for (final BitchatDevice peer in active.peerDevices) {
        int count = cached
            .where(
              (BitchatClaimedPreKey item) =>
                  item.recipientDeviceId == peer.deviceId,
            )
            .length;
        final int target = peer.prekeysAvailable.clamp(0, 3).toInt();
        while (!_wiped && count < target) {
          try {
            final BitchatClaimedPreKey claim = await repository.claimBitchatPreKey(
              gigId: gig.id,
              senderDeviceId: deviceId,
              recipientDeviceId: peer.deviceId,
            );
            if (_wiped) return;
            await _crypto.cacheClaim(gig.id, claim);
            count += 1;
          } on Object {
            break;
          }
        }
      }
    } finally {
      _prefetching = false;
    }
  }

  Future<void> _syncOwnKeys() async {
    try {
      await repository.registerBitchatDevice(
        await _crypto.registrationPayload(),
      );
    } on Object {
      // Message receipt is already durable in the encrypted local vault. Key replenishment
      // retries on the next refresh and must not turn that receipt into a failure.
    }
  }

  void _openRealtime() {
    _realtime = GigRealtimeConnection(
      repository: repository,
      gigId: gig.id,
      onState: (LiveConnectionState value) {
        _serverState = value;
        _notify();
      },
      onEvent: (GigEvent event) {
        if (event.type == 'bitchat.message') refreshInbox(silent: true);
        if (event.type == 'bitchat.panic') refreshInbox(silent: true);
      },
    )..open();
  }

  void _replaceMessage(String id, BitchatDelivery delivery) {
    final int index = _messages.indexWhere((BitchatMessage item) => item.id == id);
    if (index >= 0) _messages[index] = _messages[index].copyWith(delivery: delivery);
  }

  Future<void> _tick() async {
    final int before = _messages.length;
    _messages.removeWhere((BitchatMessage item) => item.isExpired);
    if (_messages.length != before) await _vault.save(gig.id, _messages);
    _notify();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _burnTimer?.cancel();
    unawaited(_meshMessages?.cancel());
    unawaited(_meshStates?.cancel());
    unawaited(_meshPeers?.cancel());
    unawaited(_realtime?.close());
    unawaited(_mesh.dispose());
    super.dispose();
  }
}
