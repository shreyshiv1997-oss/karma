import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../data/models/models.dart';
import 'bitchat_crypto.dart';

/// Encrypted local transcript cache with the same expiry boundary as the wire envelope.
///
/// SharedPreferences is only the blob carrier. Its contents are AES-256-GCM ciphertext; the
/// vault key is held separately in Keychain/Keystore. Expired messages are removed whenever
/// the conversation loads or the burn timer ticks.
class BitchatVault {
  BitchatVault({
    required this.userId,
    FlutterSecureStorage? storage,
    SharedPreferences? preferences,
  })  : _storage = storage ?? createBitchatSecureStorage(),
        _preferences = preferences;

  static const String _prefix = 'karma.bitchat.vault';

  final int userId;
  final FlutterSecureStorage _storage;
  SharedPreferences? _preferences;
  final AesGcm _cipher = AesGcm.with256bits();
  bool _wiped = false;

  Future<List<BitchatMessage>> load(int gigId) async {
    _ensureActive();
    final SharedPreferences prefs = await _prefs();
    final String? encoded = prefs.getString(_conversationKey(gigId));
    if (encoded == null) return <BitchatMessage>[];
    try {
      final Map<String, Object?> box = (jsonDecode(encoded) as Map)
          .map<String, Object?>((Object? key, Object? value) {
        return MapEntry<String, Object?>(key.toString(), value);
      });
      final List<int> clear = await _cipher.decrypt(
        SecretBox(
          base64Decode(box['ciphertext']! as String),
          nonce: base64Decode(box['nonce']! as String),
          mac: Mac(base64Decode(box['mac']! as String)),
        ),
        secretKey: await _vaultKey(),
        aad: utf8.encode('KARMA-BITCHAT-VAULT-V1:$userId:$gigId'),
      );
      final Object? decoded = jsonDecode(utf8.decode(clear));
      if (decoded is! List) throw const FormatException('Invalid vault payload');
      final List<BitchatMessage> messages = decoded
          .map(
            (Object? item) => BitchatMessage.fromJson(
              (item as Map).map<String, Object?>((Object? key, Object? value) {
                return MapEntry<String, Object?>(key.toString(), value);
              }),
            ),
          )
          .where((BitchatMessage item) => !item.isExpired)
          .toList(growable: false)
        ..sort(
          (BitchatMessage a, BitchatMessage b) =>
              a.sentAt.compareTo(b.sentAt),
        );
      await save(gigId, messages);
      return messages;
    } on Object {
      // Corruption or a missing/rotated vault key cannot be recovered by pretending the
      // bytes are plaintext. Remove the unreadable blob and start honestly empty.
      await prefs.remove(_conversationKey(gigId));
      return <BitchatMessage>[];
    }
  }

  Future<void> save(int gigId, Iterable<BitchatMessage> messages) async {
    if (_wiped) return;
    final SharedPreferences prefs = await _prefs();
    if (_wiped) return;
    final List<BitchatMessage> alive = messages
        .where((BitchatMessage item) => !item.isExpired)
        .toList(growable: false);
    if (alive.isEmpty) {
      await prefs.remove(_conversationKey(gigId));
      return;
    }
    final List<int> nonce = _cipher.newNonce();
    final SecretBox encrypted = await _cipher.encrypt(
      utf8.encode(
        jsonEncode(
          alive.map((BitchatMessage item) => item.toJson()).toList(growable: false),
        ),
      ),
      secretKey: await _vaultKey(),
      nonce: nonce,
      aad: utf8.encode('KARMA-BITCHAT-VAULT-V1:$userId:$gigId'),
    );
    if (_wiped) return;
    await prefs.setString(
      _conversationKey(gigId),
      jsonEncode(<String, String>{
        'nonce': base64Encode(encrypted.nonce),
        'ciphertext': base64Encode(encrypted.cipherText),
        'mac': base64Encode(encrypted.mac.bytes),
      }),
    );
    if (_wiped) await prefs.remove(_conversationKey(gigId));
  }

  Future<void> clear(int gigId) async {
    final SharedPreferences prefs = await _prefs();
    await prefs.remove(_conversationKey(gigId));
  }

  /// Physically drops every local Bitchat transcript and the key that could open it.
  Future<void> emergencyWipe() async {
    _wiped = true;
    final SharedPreferences prefs = await _prefs();
    final String conversationPrefix = '$_prefix.$userId.gig.';
    for (int pass = 0; pass < 2; pass += 1) {
      await Future.wait<bool>(
        prefs
            .getKeys()
            .where((String key) => key.startsWith(conversationPrefix))
            .map(prefs.remove),
      );
      await _storage.delete(key: '$_prefix.$userId.key');
    }
  }

  Future<BitchatMode> loadMode() async {
    final SharedPreferences prefs = await _prefs();
    final String stored = prefs.getString('$_prefix.$userId.mode') ?? 'hybrid';
    return BitchatMode.values.firstWhere(
      (BitchatMode item) => item.name == stored,
      orElse: () => BitchatMode.hybrid,
    );
  }

  Future<void> saveMode(BitchatMode mode) async {
    await (await _prefs()).setString('$_prefix.$userId.mode', mode.name);
  }

  Future<int> loadTtl() async =>
      (await _prefs()).getInt('$_prefix.$userId.ttl') ?? 3600;

  Future<void> saveTtl(int seconds) async {
    await (await _prefs()).setInt('$_prefix.$userId.ttl', seconds);
  }

  Future<SecretKey> _vaultKey() async {
    _ensureActive();
    final String keyName = '$_prefix.$userId.key';
    final String? existing = await _storage.read(key: keyName);
    _ensureActive();
    if (existing != null) return SecretKey(base64Decode(existing));
    final SecretKey key = await _cipher.newSecretKey();
    final List<int> bytes = await key.extractBytes();
    _ensureActive();
    await _storage.write(key: keyName, value: base64Encode(bytes));
    if (_wiped) {
      await _storage.delete(key: keyName);
      _ensureActive();
    }
    return key;
  }

  void _ensureActive() {
    if (_wiped) throw StateError('Bitchat vault was erased');
  }

  Future<SharedPreferences> _prefs() async =>
      _preferences ??= await SharedPreferences.getInstance();

  String _conversationKey(int gigId) => '$_prefix.$userId.gig.$gigId';
}
