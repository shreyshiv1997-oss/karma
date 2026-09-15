import 'package:intl/intl.dart';

final NumberFormat _inr = NumberFormat.currency(
  locale: 'en_IN',
  symbol: '₹',
  decimalDigits: 0,
);

String inr(num value) => _inr.format(value);

String compactDate(DateTime value) => DateFormat('d MMM yyyy').format(value.toLocal());

String relativeTime(DateTime value, {DateTime? now}) {
  final DateTime reference = now ?? DateTime.now();
  final Duration difference = reference.difference(value.toLocal());
  if (difference.isNegative || difference.inSeconds < 60) return 'just now';
  if (difference.inMinutes < 60) return '${difference.inMinutes}m';
  if (difference.inHours < 24) return '${difference.inHours}h';
  if (difference.inDays < 30) return '${difference.inDays}d';
  // Past a month the timestamp stops being a duration and becomes a date, and a date without a
  // year is a guess: an incident dismissed in 2024 and a post from last March both read "4 Mar",
  // in the two lists where telling them apart is the whole point. The year appears only when it
  // differs, so this year's rows keep the compact form; compactDate above always shows it.
  final DateTime local = value.toLocal();
  if (local.year == reference.toLocal().year) return DateFormat('d MMM').format(local);
  return DateFormat('d MMM yyyy').format(local);
}

String titleCaseStatus(String value) {
  const Map<String, String> named = <String, String>{
    'en_route': 'On the way',
    'in_progress': 'Working',
    'completion_pending': 'Awaiting approval',
    'searching': 'Searching',
    'assigned': 'Assigned',
    'arrived': 'Arrived',
    'completed': 'Completed',
    'cancelled': 'Cancelled',
  };
  return named[value] ?? value.replaceAll('_', ' ');
}
