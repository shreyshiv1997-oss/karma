import 'package:flutter_test/flutter_test.dart';
import 'package:karma_app/core/utils/formatters.dart';

void main() {
  test('relativeTime describes recent moments without false precision', () {
    final DateTime now = DateTime(2026, 9, 13, 12);
    expect(relativeTime(now.subtract(const Duration(seconds: 20)), now: now), 'just now');
    expect(relativeTime(now.subtract(const Duration(minutes: 8)), now: now), '8m');
    expect(relativeTime(now.subtract(const Duration(hours: 3)), now: now), '3h');
    expect(relativeTime(now.subtract(const Duration(days: 4)), now: now), '4d');
  });

  test('relativeTime names the year once the date is no longer this year', () {
    final DateTime now = DateTime(2026, 9, 13, 12);
    // Older than a month becomes an absolute date. This year's rows stay compact; a row from
    // another year has to say so, or a 2024 incident reads exactly like a recent post.
    expect(relativeTime(DateTime(2026, 8, 4), now: now), '4 Aug');
    expect(relativeTime(DateTime(2025, 8, 10), now: now), '10 Aug 2025');
    expect(relativeTime(DateTime(2027, 1, 2), now: now), '2 Jan 2027');
  });

  test('status formatter uses human labels', () {
    expect(titleCaseStatus('en_route'), 'On the way');
    expect(titleCaseStatus('in_progress'), 'Working');
  });
}
