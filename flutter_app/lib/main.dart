import 'package:cryptography_flutter/cryptography_flutter.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app.dart';
import 'core/network/api_client.dart';
import 'core/storage/secure_token_store.dart';
import 'data/repositories/karma_repository.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  FlutterCryptography.enable();
  await SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);

  final SharedPreferences preferences = await SharedPreferences.getInstance();
  final ApiClient api = ApiClient(tokenStore: SecureTokenStore());
  final KarmaRepository repository = KarmaRepository(
    api: api,
    preferences: preferences,
  );

  runApp(KarmaApp(repository: repository));
}
