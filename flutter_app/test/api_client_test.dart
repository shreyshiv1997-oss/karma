import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:karma_app/core/network/api_client.dart';
import 'package:karma_app/core/storage/secure_token_store.dart';
import 'package:karma_app/data/repositories/karma_repository.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _MemoryTokenStore extends SecureTokenStore {
  StoredTokens? tokens;

  @override
  Future<StoredTokens?> read() async => tokens;

  @override
  Future<void> write(StoredTokens value) async => tokens = value;

  @override
  Future<void> clear() async => tokens = null;
}

void main() {
  test('rejects non-HTTP API origins', () {
    expect(
      () => ApiClient(
        tokenStore: _MemoryTokenStore(),
        origin: 'ftp://example.com',
      ),
      throwsArgumentError,
    );
  });

  test('a failed public login does not emit authentication-lost', () async {
    final ApiClient client = ApiClient(
      tokenStore: _MemoryTokenStore(),
      origin: 'https://example.com',
      httpClient: MockClient(
        (_) async => http.Response('{"detail":"Invalid credentials"}', 401),
      ),
    );
    bool authenticationLost = false;
    client.onAuthenticationLost = () => authenticationLost = true;

    await expectLater(
      client.post('/auth/login', <String, Object?>{
        'identifier': '12345678',
        'password': 'wrong',
      }),
      throwsA(isA<ApiException>()),
    );

    expect(authenticationLost, isFalse);
    client.close();
  });

  test('an all-numeric handle is tried verbatim before phone normalization',
      () async {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    final SharedPreferences preferences = await SharedPreferences.getInstance();
    String? submittedIdentifier;
    final ApiClient client = ApiClient(
      tokenStore: _MemoryTokenStore(),
      origin: 'https://example.com',
      httpClient: MockClient((http.Request request) async {
        submittedIdentifier =
            jsonMap(jsonDecode(request.body))['identifier'] as String;
        return http.Response(jsonEncode(_authResponse('12345678')), 200);
      }),
    );
    final KarmaRepository repository = KarmaRepository(
      api: client,
      preferences: preferences,
    );

    await repository.login(identifier: '12345678', password: 'password');

    expect(submittedIdentifier, '12345678');
    client.close();
  });

  test('a formatted phone retries once in canonical form', () async {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    final SharedPreferences preferences = await SharedPreferences.getInstance();
    final List<String> attempts = <String>[];
    final ApiClient client = ApiClient(
      tokenStore: _MemoryTokenStore(),
      origin: 'https://example.com',
      httpClient: MockClient((http.Request request) async {
        final String identifier =
            jsonMap(jsonDecode(request.body))['identifier'] as String;
        attempts.add(identifier);
        if (attempts.length == 1) {
          return http.Response('{"detail":"Invalid credentials"}', 401);
        }
        return http.Response(jsonEncode(_authResponse('phone.user')), 200);
      }),
    );
    final KarmaRepository repository = KarmaRepository(
      api: client,
      preferences: preferences,
    );

    await repository.login(identifier: '98765 43210', password: 'password');

    expect(attempts, <String>['98765 43210', '+9876543210']);
    client.close();
  });
}

Map<String, Object?> _authResponse(String handle) => <String, Object?>{
      'access_token': 'access',
      'refresh_token': 'refresh',
      'user': <String, Object?>{
        'id': 1,
        'uuid': 'user-1',
        'handle': handle,
        'display_name': 'Numeric User',
        'bio': '',
        'capabilities': <String>[],
        'is_verified': false,
        'verification_tier': 'none',
        'karma': 50,
        'karma_work': 50,
        'karma_social': 50,
        'streak': 0,
        'followers_count': 0,
        'following_count': 0,
        'posts_count': 0,
      },
    };
