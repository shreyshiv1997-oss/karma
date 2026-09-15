import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karma_app/shared/widgets/primitives.dart';

void main() {
  testWidgets('Karma ring exposes its value and band to assistive technology',
      (WidgetTester tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: KarmaRing(value: 84)),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.bySemanticsLabel('Karma 84 out of 100, Proven'), findsOneWidget);
    expect(find.text('84'), findsOneWidget);
  });
}
