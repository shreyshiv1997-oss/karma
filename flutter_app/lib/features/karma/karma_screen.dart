import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../data/models/models.dart';
import '../../data/repositories/karma_repository.dart';
import '../../shared/widgets/primitives.dart';
import '../auth/session_controller.dart';

class KarmaScreen extends StatefulWidget {
  const KarmaScreen({super.key, this.refreshSignal = 0});

  final int refreshSignal;

  @override
  State<KarmaScreen> createState() => _KarmaScreenState();
}

class _KarmaScreenState extends State<KarmaScreen>
    with AutomaticKeepAliveClientMixin<KarmaScreen> {
  KarmaLedger? _ledger;
  Object? _error;
  String _domain = 'all';
  int _loadRevision = 0;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(KarmaScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.refreshSignal != widget.refreshSignal) _load();
  }

  Future<void> _load() async {
    final int revision = ++_loadRevision;
    setState(() => _error = null);
    try {
      final KarmaLedger result =
          await context.read<KarmaRepository>().karmaLedger();
      if (!mounted || revision != _loadRevision) return;
      setState(() => _ledger = result);
      try {
        await context.read<SessionController>().refreshUser();
      } on Object {
        // The ledger is authoritative and already loaded. Keep it visible if
        // the secondary user-summary refresh is temporarily unavailable.
      }
    } on Object catch (error) {
      if (mounted && revision == _loadRevision) {
        setState(() => _error = error);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    if (_ledger == null && _error == null) {
      return const ContentRail(child: LoadingCards(count: 3));
    }
    if (_error != null && _ledger == null) {
      return ContentRail(
        child: ErrorPanel(message: errorMessage(_error!), onRetry: _load),
      );
    }

    final KarmaLedger ledger = _ledger!;
    final User user = context.watch<SessionController>().user!;
    final List<KarmaEvent> events = _domain == 'all'
        ? ledger.events
        : ledger.events.where((KarmaEvent event) => event.domain == _domain).toList();

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        key: const PageStorageKey<String>('karma'),
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 112),
        children: <Widget>[
          Align(
            alignment: Alignment.topCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: AppTheme.contentMaxWidth),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  if (_error != null) ...<Widget>[
                    ErrorPanel(message: errorMessage(_error!), onRetry: _load),
                    const SizedBox(height: 13),
                  ],
                  _Hero(ledger: ledger, user: user),
                  const SizedBox(height: 13),
                  _BlendCard(ledger: ledger),
                  const SizedBox(height: 13),
                  KarmaCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: <Widget>[
                        SectionLabel(
                          'Ledger · ${ledger.totalEvents} event${ledger.totalEvents == 1 ? '' : 's'}',
                          trailing: const Icon(
                            Icons.lock_outline_rounded,
                            color: AppColors.textFaint,
                            size: 17,
                          ),
                        ),
                        const SizedBox(height: 11),
                        SingleChildScrollView(
                          scrollDirection: Axis.horizontal,
                          child: Row(
                            children: <Widget>[
                              for (final (String, String) item in const <(String, String)>[
                                ('all', 'All'),
                                ('work', 'Work'),
                                ('trust', 'Trust'),
                                ('social', 'Social'),
                                ('migration', 'Migration'),
                              ]) ...<Widget>[
                                ChoiceChip(
                                  label: Text(item.$2),
                                  selected: _domain == item.$1,
                                  onSelected: (_) => setState(() => _domain = item.$1),
                                ),
                                const SizedBox(width: 7),
                              ],
                            ],
                          ),
                        ),
                        const SizedBox(height: 8),
                        if (events.isEmpty)
                          const EmptyState(
                            icon: Icons.receipt_long_outlined,
                            title: 'No events in this view',
                            message: 'Every future change will leave an audit trail here.',
                          )
                        else
                          ...events.indexed.map(((int, KarmaEvent) item) {
                            return _EventRow(
                              event: item.$2,
                              last: item.$1 == events.length - 1,
                            );
                          }),
                        if (ledger.truncated)
                          Padding(
                            padding: const EdgeInsets.only(top: 12),
                            child: Text(
                              'Showing the ${ledger.events.length} most recent of ${ledger.totalEvents} events.',
                              style: const TextStyle(
                                color: AppColors.textFaint,
                                fontSize: 12,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Hero extends StatelessWidget {
  const _Hero({required this.ledger, required this.user});

  final KarmaLedger ledger;
  final User user;

  @override
  Widget build(BuildContext context) => KarmaCard(
        child: Column(
          children: <Widget>[
            KarmaRing(value: ledger.blended, size: 104),
            const SizedBox(height: 12),
            Text(karmaBand(ledger.blended), style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 3),
            Text(
              '${user.displayName} · @${user.handle}',
              style: const TextStyle(color: AppColors.textMuted),
            ),
            const SizedBox(height: 13),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
              decoration: BoxDecoration(
                color: AppColors.surfaceMuted,
                borderRadius: BorderRadius.circular(999),
              ),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  Icon(Icons.visibility_outlined, color: AppColors.textMuted, size: 16),
                  SizedBox(width: 6),
                  Text(
                    'Public, replayable, never edited',
                    style: TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
}

class _BlendCard extends StatelessWidget {
  const _BlendCard({required this.ledger});

  final KarmaLedger ledger;

  @override
  Widget build(BuildContext context) => KarmaCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            const SectionLabel('How it blends'),
            const SizedBox(height: 15),
            _Meter(
              label: 'Work karma',
              detail: '60% of blend',
              value: ledger.work,
              color: AppColors.lime,
            ),
            const SizedBox(height: 14),
            _Meter(
              label: 'Social karma',
              detail: '40% of blend',
              value: ledger.social,
              color: AppColors.violet,
            ),
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 15),
              child: Divider(),
            ),
            _Meter(
              label: 'Blended',
              detail: '',
              value: ledger.blended,
              color: karmaHue(ledger.blended),
              strong: true,
            ),
            const SizedBox(height: 13),
            const Text(
              'Work is weighted higher because letting someone into your home should depend on their work record — not their popularity.',
              style: TextStyle(color: AppColors.textFaint, fontSize: 12, height: 1.45),
            ),
          ],
        ),
      );
}

class _Meter extends StatelessWidget {
  const _Meter({
    required this.label,
    required this.detail,
    required this.value,
    required this.color,
    this.strong = false,
  });

  final String label;
  final String detail;
  final int value;
  final Color color;
  final bool strong;

  @override
  Widget build(BuildContext context) => Semantics(
        label: '$label $value out of 100${detail.isEmpty ? '' : ', $detail'}',
        child: Column(
          children: <Widget>[
            Row(
              children: <Widget>[
                Text(
                  label,
                  style: TextStyle(fontWeight: strong ? FontWeight.w800 : FontWeight.w600),
                ),
                if (detail.isNotEmpty)
                  Text(' · $detail', style: const TextStyle(color: AppColors.textFaint, fontSize: 12.5)),
                const Spacer(),
                Text(
                  '$value',
                  style: TextStyle(
                    color: color,
                    fontWeight: FontWeight.w800,
                    fontSize: strong ? 20 : 16,
                    fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            ClipRRect(
              borderRadius: BorderRadius.circular(999),
              child: TweenAnimationBuilder<double>(
                duration: const Duration(milliseconds: 320),
                curve: Curves.easeOutCubic,
                tween: Tween<double>(
                  begin: 0,
                  end: value.clamp(0, 100).toDouble() / 100,
                ),
                builder: (_, double animated, __) => LinearProgressIndicator(
                  value: animated,
                  minHeight: strong ? 9 : 7,
                  backgroundColor: AppColors.surfaceMuted,
                  valueColor: AlwaysStoppedAnimation<Color>(color),
                ),
              ),
            ),
          ],
        ),
      );
}

class _EventRow extends StatelessWidget {
  const _EventRow({required this.event, required this.last});

  final KarmaEvent event;
  final bool last;

  @override
  Widget build(BuildContext context) {
    final Color deltaColor = event.delta > 0
        ? AppColors.lime
        : event.delta < 0
            ? AppColors.rose
            : AppColors.textFaint;
    final Color domainColor = switch (event.domain) {
      'work' => AppColors.lime,
      'trust' => AppColors.gold,
      'social' => AppColors.violet,
      _ => AppColors.textFaint,
    };
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 12),
      decoration: BoxDecoration(
        border: last ? null : const Border(bottom: BorderSide(color: AppColors.line)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          SizedBox(
            width: 42,
            child: Text(
              '${event.delta > 0 ? '+' : ''}${event.delta}',
              style: TextStyle(
                color: deltaColor,
                fontWeight: FontWeight.w800,
                fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
              ),
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(event.reason, style: const TextStyle(fontSize: 14.5)),
                const SizedBox(height: 3),
                Text.rich(
                  TextSpan(
                    children: <InlineSpan>[
                      TextSpan(
                        text: '${event.domain[0].toUpperCase()}${event.domain.substring(1)}',
                        style: TextStyle(color: domainColor, fontWeight: FontWeight.w600),
                      ),
                      TextSpan(text: ' · ${compactDate(event.createdAt)}'),
                    ],
                  ),
                  style: const TextStyle(color: AppColors.textFaint, fontSize: 11.5),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
