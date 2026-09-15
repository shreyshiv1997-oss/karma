import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../storage/secure_token_store.dart';

class ApiException implements Exception {
  const ApiException(this.statusCode, this.detail);

  final int statusCode;
  final String detail;

  @override
  String toString() => detail;
}

class NetworkException implements Exception {
  const NetworkException([
    this.detail = 'You appear to be offline. Check your connection and try again.',
  ]);

  final String detail;

  @override
  String toString() => detail;
}

/// The only HTTP boundary in the app.
///
/// A 401 causes one refresh and one replay. Concurrent 401s share the same
/// refresh operation, so opening several tabs cannot rotate the refresh token
/// several times at once.
class ApiClient {
  ApiClient({
    required SecureTokenStore tokenStore,
    http.Client? httpClient,
    String? origin,
  })  : _tokenStore = tokenStore,
        _http = httpClient ?? http.Client(),
        _origin = _normalizeOrigin(
          origin ??
              const String.fromEnvironment(
                'API_ORIGIN',
                defaultValue: 'http://localhost:8000',
              ),
        );

  final SecureTokenStore _tokenStore;
  final http.Client _http;
  final String _origin;

  StoredTokens? _tokens;
  Completer<bool>? _refreshing;
  void Function()? onAuthenticationLost;

  String get apiBase => '$_origin/api/v1';

  Uri websocketUri(String path, [Map<String, String>? query]) {
    final Uri httpUri = Uri.parse('$apiBase$path');
    return httpUri.replace(
      scheme: httpUri.scheme == 'https' ? 'wss' : 'ws',
      queryParameters: query,
    );
  }

  Future<bool> restoreSession() async {
    _tokens = await _tokenStore.read();
    return _tokens != null;
  }

  Future<void> setTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    final StoredTokens tokens = StoredTokens(
      accessToken: accessToken,
      refreshToken: refreshToken,
    );
    _tokens = tokens;
    await _tokenStore.write(tokens);
  }

  Future<void> clearTokens() async {
    _tokens = null;
    await _tokenStore.clear();
  }

  /// Ends the session on the server as well as on this device, then forgets the tokens.
  ///
  /// [clearTokens] on its own only forgets them. The pair stays valid for the rest of its
  /// lifetime -- 60 minutes of access, 14 days of refresh -- so signing out of a phone left
  /// in a taxi, or a token copied before a "logout", still working perfectly. That is the
  /// whole reason the endpoint exists: a sign-out nobody else can see is a UI gesture.
  ///
  /// Best effort on purpose. A device with no network must still be able to sign itself out, and
  /// once the store is cleared there is nothing left here to leak. The endpoint needs no live
  /// access token, and [_mustNotRefresh] keeps this call from rotating the pair it is handing over,
  /// so the token in hand at click time is the token that dies. What stays out of reach is a pair
  /// rotated on another device -- that is POST /auth/logout-all's job, not a sign-out button's.
  Future<void> logout() async {
    final String? refreshToken = _tokens?.refreshToken;
    try {
      await post(
        '/auth/logout',
        <String, Object?>{if (refreshToken != null) 'refresh_token': refreshToken},
      );
    } on ApiException {
      // 401 here means the session was already dead; any other status means the server
      // declined to revoke. Neither is a reason to keep the tokens on this device.
    } on NetworkException {
      // Unreachable API. The local sign-out below is still the right thing to do.
    }
    await clearTokens();
  }

  Future<Object?> get(String path) => request('GET', path);

  Future<Object?> post(String path, [Map<String, Object?>? body]) =>
      request('POST', path, body: body);

  Future<Object?> patch(String path, [Map<String, Object?>? body]) =>
      request('PATCH', path, body: body);

  Future<Object?> delete(String path) => request('DELETE', path);

  Future<Object?> upload(
    String path, {
    required List<int> bytes,
    required String filename,
    required Map<String, String> fields,
  }) async {
    Future<http.Response> send() async {
      final http.MultipartRequest request = http.MultipartRequest(
        'POST',
        Uri.parse('$apiBase$path'),
      )
        ..headers['Accept'] = 'application/json'
        ..fields.addAll(fields)
        ..files.add(
          http.MultipartFile.fromBytes('file', bytes, filename: filename),
        );
      if (_tokens != null) {
        request.headers['Authorization'] = 'Bearer ${_tokens!.accessToken}';
      }
      try {
        final http.StreamedResponse streamed = await _http
            .send(request)
            .timeout(const Duration(seconds: 45));
        return http.Response.fromStream(streamed);
      } on TimeoutException {
        throw const NetworkException('The upload took too long. Try again.');
      } on http.ClientException {
        throw const NetworkException();
      }
    }

    http.Response response = await send();
    if (response.statusCode == 401 && _tokens?.refreshToken != null) {
      if (await _refresh()) response = await send();
    }
    if (response.statusCode == 401) {
      await clearTokens();
      onAuthenticationLost?.call();
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(response.statusCode, _errorDetail(response));
    }
    try {
      return _absoluteMediaUrls(jsonDecode(response.body));
    } on FormatException {
      throw ApiException(response.statusCode, 'The server returned an invalid response.');
    }
  }

  Future<Object?> request(
    String method,
    String path, {
    Map<String, Object?>? body,
  }) async {
    final bool publicAuth = _isPublicAuthPath(path);
    http.Response response = await _send(
      method,
      path,
      body: body,
      authenticated: !publicAuth,
    );

    if (response.statusCode == 401 &&
        !publicAuth &&
        _tokens?.refreshToken != null &&
        !_mustNotRefresh(path)) {
      final bool refreshed = await _refresh();
      if (refreshed) response = await _send(method, path, body: body);
    }

    if (response.statusCode == 401 && !publicAuth) {
      await clearTokens();
      onAuthenticationLost?.call();
    }

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(response.statusCode, _errorDetail(response));
    }
    if (response.statusCode == 204 || response.body.trim().isEmpty) return null;

    try {
      return _absoluteMediaUrls(jsonDecode(response.body));
    } on FormatException {
      throw ApiException(response.statusCode, 'The server returned an invalid response.');
    }
  }

  Future<http.Response> _send(
    String method,
    String path, {
    Map<String, Object?>? body,
    bool authenticated = true,
  }) async {
    final Map<String, String> headers = <String, String>{
      'Accept': 'application/json',
      'Content-Type': 'application/json',
    };
    if (authenticated && _tokens != null) {
      headers['Authorization'] = 'Bearer ${_tokens!.accessToken}';
    }

    final http.Request request = http.Request(method, Uri.parse('$apiBase$path'))
      ..headers.addAll(headers);
    if (body != null) request.body = jsonEncode(body);

    try {
      final http.StreamedResponse streamed = await _http
          .send(request)
          .timeout(const Duration(seconds: 20));
      return http.Response.fromStream(streamed);
    } on TimeoutException {
      throw const NetworkException('The server took too long to respond. Try again.');
    } on http.ClientException {
      throw const NetworkException();
    }
  }

  Future<bool> _refresh() async {
    if (_refreshing != null) return _refreshing!.future;
    final Completer<bool> completer = Completer<bool>();
    _refreshing = completer;

    try {
      final String? refreshToken = _tokens?.refreshToken;
      if (refreshToken == null) {
        completer.complete(false);
        return false;
      }
      final http.Response response = await _send(
        'POST',
        '/auth/refresh',
        body: <String, Object?>{'refresh_token': refreshToken},
        authenticated: false,
      );
      if (response.statusCode < 200 || response.statusCode >= 300) {
        await clearTokens();
        completer.complete(false);
        return false;
      }
      final Map<String, Object?> json = jsonMap(jsonDecode(response.body));
      await setTokens(
        accessToken: jsonString(json, 'access_token'),
        refreshToken: jsonString(json, 'refresh_token'),
      );
      completer.complete(true);
      return true;
    } on Object {
      if (!completer.isCompleted) completer.complete(false);
      return false;
    } finally {
      _refreshing = null;
    }
  }

  /// Paths where a transparent refresh would be actively wrong.
  ///
  /// `/auth/refresh`, because replaying it after a refresh would recurse into the same failure.
  /// `/auth/logout`, because refreshing *in order to sign out* mints a new pair while the request
  /// body still carries the old one: the server would revoke the token that was already spent and
  /// leave the new one valid for its full lifetime. A sign-out that quietly replaces the session it
  /// ends is worse than no sign-out, because it reads as success.
  static bool _mustNotRefresh(String path) =>
      path == '/auth/refresh' || path == '/auth/logout';

  static bool _isPublicAuthPath(String path) =>
      path == '/auth/login' ||
      path == '/auth/register' ||
      path == '/auth/otp/send' ||
      path == '/auth/otp/verify';

  static String _normalizeOrigin(String value) {
    final String trimmed = value.trim().replaceFirst(RegExp(r'/+$'), '');
    if (trimmed.isEmpty) return 'http://localhost:8000';
    final Uri? uri = Uri.tryParse(trimmed);
    if (uri == null ||
        !uri.hasScheme ||
        uri.host.isEmpty ||
        (uri.scheme != 'http' && uri.scheme != 'https')) {
      throw ArgumentError.value(
        value,
        'API_ORIGIN',
        'Must be an absolute HTTP(S) URL',
      );
    }
    return trimmed;
  }

  Object? _absoluteMediaUrls(Object? value) {
    if (value is String && value.startsWith('/api/v1/media/objects/')) {
      return '$_origin$value';
    }
    if (value is List) {
      return value.map<Object?>(_absoluteMediaUrls).toList(growable: false);
    }
    if (value is Map) {
      return value.map<Object?, Object?>(
        (Object? key, Object? item) => MapEntry<Object?, Object?>(
          key,
          _absoluteMediaUrls(item),
        ),
      );
    }
    return value;
  }

  static String _errorDetail(http.Response response) {
    try {
      final Object? decoded = jsonDecode(response.body);
      if (decoded is Map) {
        final Object? detail = decoded['detail'];
        if (detail is String && detail.isNotEmpty) return detail;
        if (detail is List && detail.isNotEmpty) {
          final Object? first = detail.first;
          if (first is Map && first['msg'] is String) return first['msg'] as String;
          return detail.join(', ');
        }
      }
    } on FormatException {
      // Fall back to a stable, user-facing message below.
    }
    return 'Request failed (${response.statusCode}). Please try again.';
  }

  void close() => _http.close();
}

Map<String, Object?> jsonMap(Object? value) {
  if (value is! Map) throw const FormatException('Expected a JSON object');
  return value.map<String, Object?>((Object? key, Object? item) {
    return MapEntry<String, Object?>(key.toString(), item);
  });
}

List<Object?> jsonList(Object? value) {
  if (value is! List) throw const FormatException('Expected a JSON list');
  return value.cast<Object?>();
}

String jsonString(
  Map<String, Object?> map,
  String key, {
  String fallback = '',
}) {
  final Object? value = map[key];
  return value is String ? value : fallback;
}

int jsonInt(Map<String, Object?> map, String key, {int fallback = 0}) {
  final Object? value = map[key];
  return value is num ? value.toInt() : fallback;
}

double jsonDouble(
  Map<String, Object?> map,
  String key, {
  double fallback = 0,
}) {
  final Object? value = map[key];
  return value is num ? value.toDouble() : fallback;
}

bool jsonBool(Map<String, Object?> map, String key, {bool fallback = false}) {
  final Object? value = map[key];
  return value is bool ? value : fallback;
}

List<String> jsonStrings(Map<String, Object?> map, String key) {
  final Object? value = map[key];
  if (value is! List) return <String>[];
  return value.whereType<String>().toList(growable: false);
}
