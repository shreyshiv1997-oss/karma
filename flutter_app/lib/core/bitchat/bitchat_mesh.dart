import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:universal_ble/universal_ble.dart';

import '../../data/models/models.dart';

enum BitchatMeshState { idle, starting, ready, unavailable, error }

/// A compact store-and-forward BLE mesh for already encrypted envelopes.
///
/// Nearby devices see only a random room id, random device ids, expiry, hop budget and
/// ciphertext. Frames are fragmented for the baseline 23-byte ATT MTU, deduplicated by
/// message/recipient, and relayed only while both TTL and max-hops allow it. Bluetooth is a
/// transport, never a trust boundary: the recipient still verifies Ed25519 and AES-GCM.
class BitchatMesh {
  static const String serviceUuid = 'f47b5e2d-4a9e-4c5a-9b3f-8e1d2c3a4b5c';
  static const String characteristicUuid =
      'a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d';
  static const int _headerLength = 9;
  static const int _attPayload = 20;
  static const int _chunkPayload = _attPayload - _headerLength;
  static const int _maxPackets = 128;
  static const int _maxFragments = 1024;
  static const int _maxIncomingTransfers = 32;
  static const int _maxPeers = 64;
  static const int _maxSeen = 512;

  final StreamController<BitchatEnvelope> _envelopes =
      StreamController<BitchatEnvelope>.broadcast();
  final StreamController<BitchatMeshState> _states =
      StreamController<BitchatMeshState>.broadcast();
  final StreamController<int> _peerCounts = StreamController<int>.broadcast();
  final Map<String, Map<String, Object?>> _packets =
      <String, Map<String, Object?>>{};
  final Map<String, DateTime> _peers = <String, DateTime>{};
  final Map<String, _IncomingTransfer> _incoming = <String, _IncomingTransfer>{};
  final Set<String> _seen = <String>{};
  final Set<String> _sentToPeer = <String>{};
  final Set<String> _connecting = <String>{};
  final Random _random = Random.secure();

  StreamSubscription<BleDevice>? _scanSubscription;
  Timer? _maintenance;
  BitchatMeshState _state = BitchatMeshState.idle;
  bool _disposed = false;
  bool _wiped = false;
  bool _restartingScan = false;

  Stream<BitchatEnvelope> get envelopes => _envelopes.stream;
  Stream<BitchatMeshState> get states => _states.stream;
  Stream<int> get peerCounts => _peerCounts.stream;
  BitchatMeshState get state => _state;
  int get peerCount => _peers.length;

  Future<void> start() async {
    if (_wiped || _disposed) {
      _setState(BitchatMeshState.unavailable);
      return;
    }
    if (_state == BitchatMeshState.ready ||
        _state == BitchatMeshState.starting) {
      return;
    }
    _setState(BitchatMeshState.starting);
    if (kIsWeb) {
      // Browsers can initiate Web Bluetooth connections but cannot advertise a GATT
      // peripheral, so they cannot honestly be called a mesh relay.
      _setState(BitchatMeshState.unavailable);
      return;
    }
    try {
      await UniversalBle.requestPermissions(withAndroidFineLocation: false);
      final BlePeripheralCapabilities capabilities =
          await UniversalBlePeripheral.getCapabilities();
      if (!capabilities.supportsPeripheralMode) {
        _setState(BitchatMeshState.unavailable);
        return;
      }
      final PeripheralReadinessState readiness =
          await UniversalBlePeripheral.getAvailabilityState();
      if (readiness != PeripheralReadinessState.ready) {
        _setState(BitchatMeshState.unavailable);
        return;
      }

      UniversalBlePeripheral.setWriteRequestHandlers(
        (String deviceId, String characteristicId, int _, Uint8List? value) {
          if (value != null &&
              characteristicId.toLowerCase() == characteristicUuid) {
            _acceptChunk(deviceId, value);
          }
          return PeripheralWriteRequestResult();
        },
      );
      final List<String> services = await UniversalBlePeripheral.getServices();
      if (services.any(
        (String value) => value.toLowerCase() == serviceUuid,
      )) {
        await UniversalBlePeripheral.removeService(serviceUuid);
      }
      await UniversalBlePeripheral.addService(
        BlePeripheralService(
          uuid: serviceUuid,
          characteristics: <BlePeripheralCharacteristic>[
            BlePeripheralCharacteristic(
              uuid: characteristicUuid,
              properties: <CharacteristicProperty>[
                CharacteristicProperty.write,
                CharacteristicProperty.writeWithoutResponse,
              ],
              permissions: <PeripheralAttributePermission>[
                PeripheralAttributePermission.writeable,
              ],
            ),
          ],
        ),
      );
      await UniversalBlePeripheral.startAdvertising(
        services: <String>[serviceUuid],
        localName: 'KARMA relay',
      );
      _scanSubscription ??= UniversalBle.scanStream.listen(_foundPeer);
      await _startScan();
      _maintenance = Timer.periodic(
        const Duration(seconds: 20),
        (_) => _maintain(),
      );
      _setState(BitchatMeshState.ready);
    } on Object {
      _setState(BitchatMeshState.error);
    }
  }

  Future<bool> publish(BitchatEnvelope envelope) async {
    if (_wiped ||
        _disposed ||
        envelope.isExpired ||
        envelope.hopCount > envelope.maxHops) {
      return false;
    }
    final String wireId = _wireId(envelope.messageId, envelope.recipientDeviceId);
    _seen.add(wireId);
    _trimSeen();
    _packets[wireId] = envelope.toMeshJson();
    _trimPackets();
    if (_state != BitchatMeshState.ready) await start();
    if (_state != BitchatMeshState.ready) return false;
    await _flushKnownPeers();
    // Store-and-forward is accepted even when no relay is in range yet. The encrypted
    // packet remains bounded by its TTL and will flush on the next advertisement.
    return true;
  }

  Future<void> stop() async {
    _maintenance?.cancel();
    _maintenance = null;
    await _scanSubscription?.cancel();
    _scanSubscription = null;
    try {
      await UniversalBle.stopScan();
      await UniversalBlePeripheral.stopAdvertising();
      await UniversalBlePeripheral.removeService(serviceUuid);
    } on Object {
      // Radio state can change while stopping; local teardown must still complete.
    }
    UniversalBlePeripheral.setWriteRequestHandlers(null);
    _peers.clear();
    _incoming.clear();
    _connecting.clear();
    _peerCounts.add(0);
    _setState(BitchatMeshState.idle);
  }

  Future<void> emergencyWipe() async {
    _wiped = true;
    await stop();
    _packets.clear();
    _seen.clear();
    _sentToPeer.clear();
    _incoming.clear();
  }

  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    await emergencyWipe();
    await _envelopes.close();
    await _states.close();
    await _peerCounts.close();
  }

  Future<void> _startScan() async {
    if (_restartingScan || _disposed) return;
    _restartingScan = true;
    try {
      await UniversalBle.startScan(
        scanFilter: ScanFilter(withServices: <String>[serviceUuid]),
      );
    } finally {
      _restartingScan = false;
    }
  }

  void _foundPeer(BleDevice device) {
    // The scan itself is service-filtered. CoreBluetooth may omit the advertised UUID
    // from the callback even when it matched the filter, so do not reject that iOS result.
    if (_disposed || _wiped) return;
    if (!_peers.containsKey(device.deviceId) && _peers.length >= _maxPeers) {
      final String oldest = _peers.keys.first;
      _peers.remove(oldest);
      _sentToPeer.removeWhere((String value) => value.startsWith('$oldest:'));
    }
    _peers[device.deviceId] = DateTime.now().toUtc();
    _peerCounts.add(_peers.length);
    _sendToPeer(device.deviceId);
  }

  Future<void> _sendToPeer(String peerId) async {
    if (_connecting.contains(peerId) || _disposed || _wiped) return;
    final List<MapEntry<String, Map<String, Object?>>> pending = _packets.entries
        .where(
          (MapEntry<String, Map<String, Object?>> entry) =>
              !_sentToPeer.contains('$peerId:${entry.key}'),
        )
        .toList(growable: false);
    if (pending.isEmpty) return;
    _connecting.add(peerId);
    try {
      await UniversalBle.connect(
        peerId,
        timeout: const Duration(seconds: 8),
      );
      await UniversalBle.discoverServices(peerId);
      for (final MapEntry<String, Map<String, Object?>> entry in pending) {
        final Uint8List packet = Uint8List.fromList(
          utf8.encode(jsonEncode(entry.value)),
        );
        for (final Uint8List chunk in _fragment(packet)) {
          if (_wiped || _disposed) {
            throw StateError('Mesh was erased while sending');
          }
          await UniversalBle.write(
            peerId,
            serviceUuid,
            characteristicUuid,
            chunk,
            timeout: const Duration(seconds: 5),
          );
        }
        _sentToPeer.add('$peerId:${entry.key}');
      }
    } on Object {
      // Discovery is best effort. The packet remains queued until its TTL and a later
      // advertisement can retry it.
    } finally {
      try {
        await UniversalBle.disconnect(
          peerId,
          timeout: const Duration(seconds: 3),
        );
      } on Object {
        // Ignore teardown races.
      }
      _connecting.remove(peerId);
    }
  }

  Future<void> _flushKnownPeers() async {
    for (final String peer in _peers.keys.toList(growable: false)) {
      await _sendToPeer(peer);
    }
  }

  List<Uint8List> _fragment(Uint8List packet) {
    final int total = (packet.length / _chunkPayload).ceil();
    if (total == 0 || total > _maxFragments) {
      throw const FormatException('Mesh packet is outside the supported size');
    }
    final int transferId = _random.nextInt(0xffffffff);
    return List<Uint8List>.generate(total, (int index) {
      final int start = index * _chunkPayload;
      final int end = min(start + _chunkPayload, packet.length);
      final Uint8List output = Uint8List(_headerLength + end - start);
      final ByteData header = ByteData.sublistView(output);
      header.setUint8(0, 1);
      header.setUint32(1, transferId);
      header.setUint16(5, index);
      header.setUint16(7, total);
      output.setRange(_headerLength, output.length, packet.sublist(start, end));
      return output;
    }, growable: false);
  }

  void _acceptChunk(String peerId, Uint8List chunk) {
    if (_wiped ||
        _disposed ||
        chunk.length <= _headerLength ||
        chunk.length > _attPayload ||
        chunk[0] != 1) {
      return;
    }
    final ByteData header = ByteData.sublistView(chunk);
    final int transferId = header.getUint32(1);
    final int index = header.getUint16(5);
    final int total = header.getUint16(7);
    if (total == 0 || index >= total || total > _maxFragments) return;
    final String key = '$peerId:$transferId';
    if (!_incoming.containsKey(key) &&
        _incoming.length >= _maxIncomingTransfers) {
      return;
    }
    final _IncomingTransfer transfer = _incoming.putIfAbsent(
      key,
      () => _IncomingTransfer(total),
    );
    if (transfer.total != total) {
      _incoming.remove(key);
      return;
    }
    transfer.add(index, Uint8List.sublistView(chunk, _headerLength));
    if (!transfer.complete) return;
    _incoming.remove(key);
    try {
      final Object? decoded = jsonDecode(utf8.decode(transfer.bytes));
      if (decoded is! Map) return;
      final Map<String, Object?> packet = decoded.map<String, Object?>(
        (Object? key, Object? value) => MapEntry<String, Object?>(
          key.toString(),
          value,
        ),
      );
      final BitchatEnvelope envelope = BitchatEnvelope.fromJson(packet);
      final String wireId = _wireId(
        envelope.messageId,
        envelope.recipientDeviceId,
      );
      if (envelope.isExpired || _seen.contains(wireId)) return;
      _seen.add(wireId);
      _trimSeen();
      _envelopes.add(envelope);
      if (envelope.hopCount < envelope.maxHops) {
        _packets[wireId] = envelope.toMeshJson(hops: envelope.hopCount + 1);
        _trimPackets();
        _flushKnownPeers();
      }
    } on Object {
      // Malformed frames are untrusted radio input. Drop them without affecting the mesh.
    }
  }

  void _maintain() {
    final DateTime now = DateTime.now().toUtc();
    final List<String> expiredPeers = _peers.entries
        .where(
          (MapEntry<String, DateTime> entry) =>
              now.difference(entry.value) > const Duration(minutes: 2),
        )
        .map((MapEntry<String, DateTime> entry) => entry.key)
        .toList(growable: false);
    for (final String peer in expiredPeers) {
      _peers.remove(peer);
      _sentToPeer.removeWhere((String value) => value.startsWith('$peer:'));
    }
    _incoming.removeWhere(
      (_, _IncomingTransfer transfer) =>
          now.difference(transfer.startedAt) > const Duration(seconds: 30),
    );
    _packets.removeWhere((String id, Map<String, Object?> packet) {
      final DateTime? expiry = DateTime.tryParse('${packet['expires_at']}');
      final bool remove = expiry == null || !expiry.isAfter(now);
      if (remove) {
        _sentToPeer.removeWhere((String value) => value.endsWith(':$id'));
      }
      return remove;
    });
    _peerCounts.add(_peers.length);
    _flushKnownPeers();
  }

  void _trimPackets() {
    while (_packets.length > _maxPackets) {
      final String oldest = _packets.keys.first;
      _packets.remove(oldest);
      _sentToPeer.removeWhere((String value) => value.endsWith(':$oldest'));
    }
  }

  void _trimSeen() {
    while (_seen.length > _maxSeen) {
      _seen.remove(_seen.first);
    }
  }

  void _setState(BitchatMeshState state) {
    _state = state;
    if (!_disposed) _states.add(state);
  }

  static String _wireId(String messageId, String recipientDeviceId) =>
      '$messageId:$recipientDeviceId';
}

class _IncomingTransfer {
  _IncomingTransfer(this.total)
      : chunks = List<Uint8List?>.filled(total, null, growable: false);

  final int total;
  final List<Uint8List?> chunks;
  final DateTime startedAt = DateTime.now().toUtc();

  bool get complete => chunks.every((Uint8List? item) => item != null);

  void add(int index, Uint8List value) {
    chunks[index] ??= Uint8List.fromList(value);
  }

  Uint8List get bytes {
    final BytesBuilder builder = BytesBuilder(copy: false);
    for (final Uint8List? chunk in chunks) {
      if (chunk == null) throw StateError('Transfer is incomplete');
      builder.add(chunk);
    }
    return builder.takeBytes();
  }
}
