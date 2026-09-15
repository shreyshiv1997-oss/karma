import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../data/models/models.dart';

FlutterSecureStorage createBitchatSecureStorage() =>
    const FlutterSecureStorage(
      aOptions: AndroidOptions(encryptedSharedPreferences: true),
      iOptions: IOSOptions(
        accessibility: KeychainAccessibility.first_unlock_this_device,
      ),
    );

/// Client-only cryptographic boundary for Bitchat.
///
/// The backend receives Ed25519 public identities, signed one-time X25519 prekeys and
/// AES-256-GCM envelopes. Identity seeds, one-time private keys and local vault keys stay in
/// Keychain/Keystore-backed secure storage. A used prekey is deleted only after authenticated
/// decryption succeeds, so a crash cannot turn a recoverable message into permanent loss.
class BitchatCrypto {
  BitchatCrypto({
    required this.userId,
    FlutterSecureStorage? storage,
  }) : _storage = storage ?? createBitchatSecureStorage();

  static const int targetPrekeys = 24;
  static const String _prefix = 'karma.bitchat';

  final int userId;
  final FlutterSecureStorage _storage;
  final Ed25519 _signing = Ed25519();
  final X25519 _exchange = X25519();
  final AesGcm _cipher = AesGcm.with256bits();
  final Hkdf _kdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);
  final Random _random = Random.secure();

  SimpleKeyPair? _identity;
  String? _deviceId;
  int _nextPrekeyId = 1;
  final Map<int, SimpleKeyPair> _prekeys = <int, SimpleKeyPair>{};
  bool _wiped = false;

  String get deviceId {
    final String? value = _deviceId;
    if (value == null) throw StateError('Bitchat identity is not initialized');
    return value;
  }

  String newMessageId() => _uuid();

  Future<void> initialize() async {
    _ensureActive();
    if (_identity != null) return;
    final String identityKey = '$_prefix.$userId.identity';
    final String deviceKey = '$_prefix.$userId.device';
    final String nextKey = '$_prefix.$userId.next_prekey';
    final String? encodedSeed = await _storage.read(key: identityKey);
    _ensureActive();

    final SimpleKeyPair identity;
    if (encodedSeed == null) {
      identity = await _signing.newKeyPair();
      _ensureActive();
      final List<int> seed = await identity.extractPrivateKeyBytes();
      _ensureActive();
      await _storage.write(key: identityKey, value: base64Encode(seed));
      if (_wiped) {
        await _storage.delete(key: identityKey);
        _ensureActive();
      }
    } else {
      identity = await _signing.newKeyPairFromSeed(base64Decode(encodedSeed));
      _ensureActive();
    }
    _identity = identity;

    String? currentDeviceId = await _storage.read(key: deviceKey);
    _ensureActive();
    if (currentDeviceId == null) {
      currentDeviceId = _uuid();
      await _storage.write(key: deviceKey, value: currentDeviceId);
      if (_wiped) {
        await _storage.delete(key: deviceKey);
        _ensureActive();
      }
    }
    _deviceId = currentDeviceId;
    final String? encodedNext = await _storage.read(key: nextKey);
    _ensureActive();
    _nextPrekeyId = int.tryParse(encodedNext ?? '') ?? 1;

    final Map<String, String> all = await _storage.readAll();
    _ensureActive();
    final String prekeyPrefix = '$_prefix.$userId.$currentDeviceId.prekey.';
    for (final MapEntry<String, String> entry in all.entries) {
      _ensureActive();
      if (!entry.key.startsWith(prekeyPrefix)) continue;
      final int? id = int.tryParse(entry.key.substring(prekeyPrefix.length));
      if (id == null) continue;
      final SimpleKeyPair pair =
          await _exchange.newKeyPairFromSeed(base64Decode(entry.value));
      _ensureActive();
      _prekeys[id] = pair;
    }
    await _replenish();
  }

  Future<Map<String, Object?>> registrationPayload() async {
    await initialize();
    final SimplePublicKey publicKey = await _identity!.extractPublicKey();
    _ensureActive();
    final List<Map<String, Object?>> registrations = <Map<String, Object?>>[];
    for (final MapEntry<int, SimpleKeyPair> entry in _prekeys.entries) {
      final SimplePublicKey prekey = await entry.value.extractPublicKey();
      final String encoded = base64Encode(prekey.bytes);
      final List<int> signature = await _sign(
        utf8.encode(_prekeyCanonical(deviceId, entry.key, encoded)),
      );
      registrations.add(<String, Object?>{
        'key_id': entry.key,
        'public_key': encoded,
        'signature': base64Encode(signature),
      });
    }
    registrations.sort(
      (Map<String, Object?> a, Map<String, Object?> b) =>
          (a['key_id']! as int).compareTo(b['key_id']! as int),
    );
    _ensureActive();
    return <String, Object?>{
      'device_id': deviceId,
      'label': kIsWeb ? 'Web browser' : '${defaultTargetPlatform.name} device',
      'identity_key': base64Encode(publicKey.bytes),
      'prekeys': registrations,
    };
  }

  Future<void> cacheSession(BitchatSession session) async {
    await initialize();
    final String key = '$_prefix.$userId.session.${session.gigId}';
    _ensureActive();
    await _storage.write(key: key, value: jsonEncode(session.toJson()));
    if (_wiped) await _storage.delete(key: key);
  }

  Future<BitchatSession?> cachedSession(int gigId) async {
    await initialize();
    final String? encoded = await _storage.read(
      key: '$_prefix.$userId.session.$gigId',
    );
    _ensureActive();
    if (encoded == null) return null;
    try {
      return BitchatSession.fromJson(
        (jsonDecode(encoded) as Map).map<String, Object?>(
          (Object? key, Object? value) => MapEntry<String, Object?>(
            key.toString(),
            value,
          ),
        ),
      );
    } on Object {
      await _storage.delete(key: '$_prefix.$userId.session.$gigId');
      return null;
    }
  }

  Future<void> cacheClaim(int gigId, BitchatClaimedPreKey claim) async {
    final List<BitchatClaimedPreKey> claims = await cachedClaims(gigId);
    if (claims.any(
      (BitchatClaimedPreKey item) =>
          item.recipientDeviceId == claim.recipientDeviceId &&
          item.keyId == claim.keyId,
    )) {
      return;
    }
    claims.add(claim);
    await _writeClaims(gigId, claims);
  }

  Future<List<BitchatClaimedPreKey>> cachedClaims(int gigId) async {
    await initialize();
    final String? encoded = await _storage.read(
      key: '$_prefix.$userId.claims.$gigId',
    );
    _ensureActive();
    if (encoded == null) return <BitchatClaimedPreKey>[];
    try {
      final Object? decoded = jsonDecode(encoded);
      if (decoded is! List) return <BitchatClaimedPreKey>[];
      return decoded
          .map(
            (Object? item) => BitchatClaimedPreKey.fromJson(
              (item as Map).map<String, Object?>(
                (Object? key, Object? value) => MapEntry<String, Object?>(
                  key.toString(),
                  value,
                ),
              ),
            ),
          )
          .toList(growable: true);
    } on Object {
      await _storage.delete(key: '$_prefix.$userId.claims.$gigId');
      return <BitchatClaimedPreKey>[];
    }
  }

  Future<BitchatClaimedPreKey?> takeCachedClaim(
    int gigId,
    String recipientDeviceId,
  ) async {
    final List<BitchatClaimedPreKey> claims = await cachedClaims(gigId);
    final int index = claims.indexWhere(
      (BitchatClaimedPreKey item) =>
          item.recipientDeviceId == recipientDeviceId,
    );
    if (index < 0) return null;
    final BitchatClaimedPreKey result = claims.removeAt(index);
    await _writeClaims(gigId, claims);
    return result;
  }

  Future<void> _writeClaims(
    int gigId,
    List<BitchatClaimedPreKey> claims,
  ) async {
    _ensureActive();
    final String key = '$_prefix.$userId.claims.$gigId';
    if (claims.isEmpty) {
      await _storage.delete(key: key);
      return;
    }
    await _storage.write(
      key: key,
      value: jsonEncode(
        claims
            .map((BitchatClaimedPreKey item) => item.toJson())
            .toList(growable: false),
      ),
    );
    if (_wiped) await _storage.delete(key: key);
  }

  Future<BitchatEnvelope> encrypt({
    required String messageId,
    required int gigId,
    required String roomId,
    required BitchatClaimedPreKey claimed,
    required String plaintext,
    required int ttlSeconds,
    required int maxHops,
    required BitchatMode mode,
  }) async {
    await initialize();
    if (plaintext.trim().isEmpty || plaintext.length > 1500) {
      throw ArgumentError('Messages must contain 1 to 1500 characters');
    }
    await _verifyPrekey(claimed);

    final SimpleKeyPair ephemeral = await _exchange.newKeyPair();
    final SimplePublicKey ephemeralPublic = await ephemeral.extractPublicKey();
    final String encodedEphemeral = base64Encode(ephemeralPublic.bytes);
    final DateTime sentAt = DateTime.now().toUtc();
    final DateTime expiresAt = sentAt.add(Duration(seconds: ttlSeconds));
    final List<int> nonce = _cipher.newNonce();
    final String aad = envelopeAad(
      messageId: messageId,
      roomId: roomId,
      senderDeviceId: deviceId,
      recipientDeviceId: claimed.recipientDeviceId,
      prekeyId: claimed.keyId,
      ephemeralKey: encodedEphemeral,
      sentAt: sentAt,
      ttlSeconds: ttlSeconds,
      maxHops: maxHops,
    );
    final SecretKey shared = await _exchange.sharedSecretKey(
      keyPair: ephemeral,
      remotePublicKey: SimplePublicKey(
        base64Decode(claimed.publicKey),
        type: KeyPairType.x25519,
      ),
    );
    final SecretKey messageKey = await _kdf.deriveKey(
      secretKey: shared,
      nonce: nonce,
      info: utf8.encode(aad),
    );
    final SecretBox box = await _cipher.encrypt(
      utf8.encode(plaintext),
      secretKey: messageKey,
      nonce: nonce,
      aad: utf8.encode(aad),
    );
    final String encodedNonce = base64Encode(box.nonce);
    final String ciphertext = base64Encode(box.cipherText);
    final String mac = base64Encode(box.mac.bytes);
    final List<int> signature = await _sign(
      utf8.encode('$aad\n$encodedNonce\n$ciphertext\n$mac'),
    );
    final SimplePublicKey identityPublic = await _identity!.extractPublicKey();
    return BitchatEnvelope(
      messageId: messageId,
      gigId: gigId,
      roomId: roomId,
      senderDeviceId: deviceId,
      senderIdentityKey: base64Encode(identityPublic.bytes),
      recipientDeviceId: claimed.recipientDeviceId,
      prekeyId: claimed.keyId,
      ephemeralKey: encodedEphemeral,
      nonce: encodedNonce,
      ciphertext: ciphertext,
      mac: mac,
      signature: base64Encode(signature),
      sentAt: sentAt,
      expiresAt: expiresAt,
      ttlSeconds: ttlSeconds,
      maxHops: maxHops,
      transport: mode.name,
    );
  }

  Future<String> decrypt(
    BitchatEnvelope envelope, {
    required String expectedIdentityKey,
  }) async {
    await initialize();
    if (envelope.recipientDeviceId != deviceId) {
      throw const FormatException('Envelope is addressed to another device');
    }
    if (envelope.isExpired) throw const FormatException('Envelope expired');
    if (envelope.senderIdentityKey != expectedIdentityKey) {
      throw const FormatException('Peer identity changed');
    }
    final String aad = envelopeAad(
      messageId: envelope.messageId,
      roomId: envelope.roomId,
      senderDeviceId: envelope.senderDeviceId,
      recipientDeviceId: envelope.recipientDeviceId,
      prekeyId: envelope.prekeyId,
      ephemeralKey: envelope.ephemeralKey,
      sentAt: envelope.sentAt,
      ttlSeconds: envelope.ttlSeconds,
      maxHops: envelope.maxHops,
    );
    final bool authentic = await _signing.verify(
      utf8.encode(
        '$aad\n${envelope.nonce}\n${envelope.ciphertext}\n${envelope.mac}',
      ),
      signature: Signature(
        base64Decode(envelope.signature),
        publicKey: SimplePublicKey(
          base64Decode(expectedIdentityKey),
          type: KeyPairType.ed25519,
        ),
      ),
    );
    if (!authentic) throw const FormatException('Envelope signature is invalid');

    final SimpleKeyPair? prekey = _prekeys[envelope.prekeyId];
    if (prekey == null) {
      throw const FormatException('One-time decryption key is unavailable');
    }
    final List<int> nonce = base64Decode(envelope.nonce);
    final SecretKey shared = await _exchange.sharedSecretKey(
      keyPair: prekey,
      remotePublicKey: SimplePublicKey(
        base64Decode(envelope.ephemeralKey),
        type: KeyPairType.x25519,
      ),
    );
    final SecretKey messageKey = await _kdf.deriveKey(
      secretKey: shared,
      nonce: nonce,
      info: utf8.encode(aad),
    );
    final List<int> clear = await _cipher.decrypt(
      SecretBox(
        base64Decode(envelope.ciphertext),
        nonce: nonce,
        mac: Mac(base64Decode(envelope.mac)),
      ),
      secretKey: messageKey,
      aad: utf8.encode(aad),
    );
    final String plaintext = utf8.decode(clear);
    _ensureActive();
    await _consumePrekey(envelope.prekeyId);
    await _replenish();
    _ensureActive();
    return plaintext;
  }

  Future<void> emergencyWipe() async {
    _wiped = true;
    final String userPrefix = '$_prefix.$userId.';
    // Two passes catch a secure-storage write that was already in flight when panic
    // started. All writers also delete their just-written value when they observe wipe.
    for (int pass = 0; pass < 2; pass += 1) {
      final Map<String, String> values = await _storage.readAll();
      await Future.wait<void>(
        values.keys
            .where((String key) => key.startsWith(userPrefix))
            .map((String key) => _storage.delete(key: key)),
      );
    }
    _identity = null;
    _deviceId = null;
    _prekeys.clear();
    _nextPrekeyId = 1;
  }

  Future<void> _replenish() async {
    _ensureActive();
    while (!_wiped && _prekeys.length < targetPrekeys) {
      final int id = _nextPrekeyId++;
      final SimpleKeyPair pair = await _exchange.newKeyPair();
      _ensureActive();
      _prekeys[id] = pair;
      final List<int> seed = await pair.extractPrivateKeyBytes();
      _ensureActive();
      final String key = '$_prefix.$userId.$deviceId.prekey.$id';
      await _storage.write(key: key, value: base64Encode(seed));
      if (_wiped) {
        _prekeys.remove(id);
        await _storage.delete(key: key);
        _ensureActive();
      }
    }
    _ensureActive();
    final String nextKey = '$_prefix.$userId.next_prekey';
    await _storage.write(key: nextKey, value: '$_nextPrekeyId');
    if (_wiped) {
      await _storage.delete(key: nextKey);
      _ensureActive();
    }
  }

  Future<void> _consumePrekey(int id) async {
    _prekeys.remove(id);
    await _storage.delete(key: '$_prefix.$userId.$deviceId.prekey.$id');
  }

  Future<void> _verifyPrekey(BitchatClaimedPreKey claimed) async {
    final bool valid = await _signing.verify(
      utf8.encode(
        _prekeyCanonical(
          claimed.recipientDeviceId,
          claimed.keyId,
          claimed.publicKey,
        ),
      ),
      signature: Signature(
        base64Decode(claimed.signature),
        publicKey: SimplePublicKey(
          base64Decode(claimed.recipientIdentityKey),
          type: KeyPairType.ed25519,
        ),
      ),
    );
    if (!valid) throw const FormatException('Peer prekey signature is invalid');
  }

  Future<List<int>> _sign(List<int> bytes) async {
    _ensureActive();
    final Signature signature = await _signing.sign(
      bytes,
      keyPair: _identity!,
    );
    _ensureActive();
    return signature.bytes;
  }

  void _ensureActive() {
    if (_wiped) throw StateError('Bitchat key material was erased');
  }

  String _uuid() {
    final Uint8List bytes = Uint8List.fromList(
      List<int>.generate(16, (_) => _random.nextInt(256)),
    );
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    final String hex = bytes
        .map((int value) => value.toRadixString(16).padLeft(2, '0'))
        .join();
    return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
        '${hex.substring(12, 16)}-${hex.substring(16, 20)}-'
        '${hex.substring(20)}';
  }

  static String _prekeyCanonical(String deviceId, int keyId, String publicKey) =>
      'KARMA-BITCHAT-PREKEY-V1\n$deviceId\n$keyId\n$publicKey';

  static String envelopeAad({
    required String messageId,
    required String roomId,
    required String senderDeviceId,
    required String recipientDeviceId,
    required int prekeyId,
    required String ephemeralKey,
    required DateTime sentAt,
    required int ttlSeconds,
    required int maxHops,
  }) =>
      <String>[
        'KARMA-BITCHAT-AAD-V1',
        messageId,
        roomId,
        senderDeviceId,
        recipientDeviceId,
        '$prekeyId',
        ephemeralKey,
        '${sentAt.toUtc().millisecondsSinceEpoch ~/ 1000}',
        '$ttlSeconds',
        '$maxHops',
      ].join('\n');
}
