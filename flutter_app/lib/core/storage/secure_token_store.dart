import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class StoredTokens {
  const StoredTokens({required this.accessToken, required this.refreshToken});

  final String accessToken;
  final String refreshToken;
}

/// Credentials are deliberately separate from preferences and feed caches.
class SecureTokenStore {
  SecureTokenStore({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
              iOptions: IOSOptions(
                accessibility: KeychainAccessibility.first_unlock_this_device,
              ),
            );

  static const String _accessKey = 'karma.access_token';
  static const String _refreshKey = 'karma.refresh_token';

  final FlutterSecureStorage _storage;

  Future<StoredTokens?> read() async {
    final List<String?> values = await Future.wait<String?>(<Future<String?>>[
      _storage.read(key: _accessKey),
      _storage.read(key: _refreshKey),
    ]);
    if (values[0] == null || values[1] == null) return null;
    return StoredTokens(accessToken: values[0]!, refreshToken: values[1]!);
  }

  Future<void> write(StoredTokens tokens) async {
    await Future.wait<void>(<Future<void>>[
      _storage.write(key: _accessKey, value: tokens.accessToken),
      _storage.write(key: _refreshKey, value: tokens.refreshToken),
    ]);
  }

  Future<void> clear() async {
    await Future.wait<void>(<Future<void>>[
      _storage.delete(key: _accessKey),
      _storage.delete(key: _refreshKey),
    ]);
  }
}
