import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karma_app/shared/widgets/proof_comparison.dart';

void main() {
  testWidgets('before-image reveal tracks the comparison handle',
      (WidgetTester tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 300,
              child: ProofComparison(
                beforeUrl: 'https://example.invalid/before.jpg',
                afterUrl: 'https://example.invalid/after.jpg',
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    Positioned revealViewport() => tester
        .widgetList<Positioned>(find.byType(Positioned))
        .singleWhere(
          (Positioned widget) =>
              widget.left == 0 && widget.top == 0 && widget.width != null,
        );

    expect(revealViewport().width, moreOrLessEquals(150));

    final Rect comparison = tester.getRect(find.byType(ProofComparison));
    await tester.tapAt(
      Offset(comparison.left + comparison.width * 0.25, comparison.center.dy),
    );
    await tester.pump();

    expect(revealViewport().width, moreOrLessEquals(75));
  });
}
