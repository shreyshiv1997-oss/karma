import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/theme/app_theme.dart';
import 'data/repositories/karma_repository.dart';
import 'features/auth/auth_screen.dart';
import 'features/auth/session_controller.dart';
import 'features/shell/app_shell.dart';
import 'shared/widgets/primitives.dart';

class KarmaApp extends StatelessWidget {
  const KarmaApp({required this.repository, super.key});

  final KarmaRepository repository;

  @override
  Widget build(BuildContext context) => MultiProvider(
        providers: [
          Provider<KarmaRepository>.value(value: repository),
          ChangeNotifierProvider<SessionController>(
            create: (_) => SessionController(repository)..initialize(),
          ),
        ],
        child: MaterialApp(
          title: 'KARMA',
          debugShowCheckedModeBanner: false,
          theme: AppTheme.light(),
          themeMode: ThemeMode.light,
          home: const _SessionGate(),
        ),
      );
}

class _SessionGate extends StatelessWidget {
  const _SessionGate();

  @override
  Widget build(BuildContext context) {
    final SessionStatus status = context.watch<SessionController>().status;
    return AnimatedSwitcher(
      duration: AppTheme.enter,
      child: switch (status) {
        SessionStatus.loading => const _LaunchScreen(key: ValueKey<String>('loading')),
        SessionStatus.signedOut => const AuthScreen(key: ValueKey<String>('auth')),
        SessionStatus.signedIn => const AppShell(key: ValueKey<String>('shell')),
      },
    );
  }
}

class _LaunchScreen extends StatelessWidget {
  const _LaunchScreen({super.key});

  @override
  Widget build(BuildContext context) => const Scaffold(
        backgroundColor: AppColors.ink,
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              KarmaRing(value: 88, size: 72),
              SizedBox(height: 14),
              Text(
                'KARMA',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 23,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 2,
                ),
              ),
            ],
          ),
        ),
      );
}
