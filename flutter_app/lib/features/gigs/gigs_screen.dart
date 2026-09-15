import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../core/network/gig_realtime.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../data/models/models.dart';
import '../../data/repositories/karma_repository.dart';
import '../../data/services/device_capabilities_service.dart';
import '../../data/services/payment_sheet_service.dart';
import '../../shared/widgets/primitives.dart';
import '../auth/session_controller.dart';
import '../bitchat/bitchat_screen.dart';

class GigsScreen extends StatefulWidget {
  const GigsScreen({required this.onPostGig, super.key, this.refreshSignal = 0});

  final VoidCallback onPostGig;
  final int refreshSignal;

  @override
  State<GigsScreen> createState() => _GigsScreenState();
}

class _GigsScreenState extends State<GigsScreen>
    with AutomaticKeepAliveClientMixin<GigsScreen> {
  String _role = 'customer';
  List<Gig>? _gigs;
  GigStats? _stats;
  Object? _error;
  int? _busyGig;
  LiveConnectionState _liveState = LiveConnectionState.paused;
  GigRealtimeConnection? _live;
  int? _subscribedGig;
  int _loadRevision = 0;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(GigsScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.refreshSignal != widget.refreshSignal) _load();
  }

  @override
  void dispose() {
    _live?.close();
    super.dispose();
  }

  Future<void> _load({bool showLoading = false}) async {
    if (showLoading) setState(() => _gigs = null);
    setState(() => _error = null);
    final int revision = ++_loadRevision;
    final String requestedRole = _role;
    final KarmaRepository repository = context.read<KarmaRepository>();
    Object? firstError;

    Future<T?> capture<T>(Future<T> request) async {
      try {
        return await request;
      } on Object catch (error) {
        firstError ??= error;
        return null;
      }
    }

    final List<Object?> results = await Future.wait<Object?>(<Future<Object?>>[
      capture<List<Gig>>(repository.gigs(role: requestedRole)),
      capture<GigStats>(repository.gigStats()),
    ]);
    if (!mounted || revision != _loadRevision || requestedRole != _role) return;
    setState(() {
      if (results[0] != null) _gigs = results[0]! as List<Gig>;
      if (results[1] != null) _stats = results[1]! as GigStats;
      _error = firstError;
    });
    if (results[0] != null) _connectLive();
  }

  void _connectLive() {
    final Gig? active = _gigs?.where((Gig gig) => gig.isActive).firstOrNull;
    if (active?.id == _subscribedGig) return;
    _live?.close();
    _subscribedGig = active?.id;
    if (active == null) {
      setState(() => _liveState = LiveConnectionState.paused);
      return;
    }
    _live = GigRealtimeConnection(
      repository: context.read<KarmaRepository>(),
      gigId: active.id,
      onState: (LiveConnectionState value) {
        if (mounted && _subscribedGig == active.id) {
          setState(() => _liveState = value);
        }
      },
      onEvent: (GigEvent event) {
        if (_subscribedGig == active.id && event.type.startsWith('gig.')) {
          _load();
        }
      },
    )..open();
  }

  Future<void> _advance(Gig gig) async {
    const Map<String, String> next = <String, String>{
      'assigned': 'en_route',
      'en_route': 'arrived',
      'arrived': 'in_progress',
      'in_progress': 'completion_pending',
    };
    final String? status = next[gig.status];
    if (status == null) return;

    List<String> proof = const <String>[];
    if (status == 'completion_pending') {
      final List<String>? submitted = await showModalBottomSheet<List<String>>(
        context: context,
        isScrollControlled: true,
        useSafeArea: true,
        showDragHandle: true,
        builder: (BuildContext context) => const _ProofSubmissionSheet(),
      );
      if (submitted == null || !mounted) return;
      proof = submitted;
    }

    setState(() {
      _busyGig = gig.id;
      _error = null;
    });
    try {
      final Gig updated = await context.read<KarmaRepository>().updateGigStatus(
            gig.id,
            status,
            proofPhotos: proof,
          );
      if (mounted) {
        setState(() {
          _gigs = _gigs
              ?.map((Gig item) => item.id == updated.id ? updated : item)
              .toList(growable: false);
        });
      }
      if (status == 'completion_pending') {
        HapticFeedback.heavyImpact();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'Proof submitted. Payment stays secured until the customer approves the work.',
              ),
            ),
          );
        }
      }
      await _load();
    } on Object catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busyGig = null);
    }
  }

  Future<void> _securePayment(Gig gig) async {
    setState(() {
      _busyGig = gig.id;
      _error = null;
    });
    try {
      final PaymentSheetService payments =
          PaymentSheetService(context.read<KarmaRepository>());
      final GigPayment payment = await payments.secure(gig.id);
      if (!mounted) return;
      HapticFeedback.mediumImpact();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            payment.provider == 'stripe'
                ? 'Payment secured by Stripe. You will be charged only after approval.'
                : 'Test payment secured. No real charge was made.',
          ),
        ),
      );
      await _load();
    } on Object catch (error) {
      if (mounted && !isPaymentSheetCancellation(error)) {
        setState(() => _error = error);
      }
    } finally {
      if (mounted) setState(() => _busyGig = null);
    }
  }

  Future<void> _releasePayment(Gig gig) async {
    final bool confirmed = await _confirm(
      title: 'Approve the completed work?',
      message:
          '${inr(gig.total)} will be captured through Stripe and released to the worker. '
          'Use “Open a dispute” instead if the work is not acceptable.',
      action: 'Approve & release',
      destructive: false,
    );
    if (!confirmed || !mounted) return;
    setState(() {
      _busyGig = gig.id;
      _error = null;
    });
    try {
      final GigPayment payment = await PaymentSheetService(
        context.read<KarmaRepository>(),
      ).release(gig.id);
      if (!mounted) return;
      HapticFeedback.heavyImpact();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${inr(payment.amount)} released. The proof and worker payout are now final.',
          ),
        ),
      );
      await _load();
    } on Object catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busyGig = null);
    }
  }

  void _openBitchat(Gig gig) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (BuildContext context) => BitchatScreen(gig: gig),
      ),
    );
  }

  Future<void> _sos(Gig gig) async {
    HapticFeedback.heavyImpact();
    try {
      await context.read<KarmaRepository>().emergency(gigId: gig.id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          duration: Duration(seconds: 5),
          content: Text('Emergency signal sent to your contacts and the safety team.'),
        ),
      );
    } on Object catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(errorMessage(error))),
      );
    }
  }

  Future<void> _cancel(Gig gig) async {
    final bool confirmed = await _confirm(
      title: 'Cancel this gig?',
      message: 'The other party will see the cancellation immediately.',
      action: 'Cancel gig',
    );
    if (!confirmed || !mounted) return;
    setState(() => _busyGig = gig.id);
    try {
      final Gig updated = await context
          .read<KarmaRepository>()
          .updateGigStatus(gig.id, 'cancelled');
      if (mounted) {
        setState(() {
          _gigs = _gigs
              ?.map((Gig item) => item.id == updated.id ? updated : item)
              .toList(growable: false);
        });
      }
      await _load();
    } on Object catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busyGig = null);
    }
  }

  Future<void> _dispute(Gig gig) async {
    final TextEditingController controller = TextEditingController();
    final String? reason = await showDialog<String>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: const Text('Open a dispute'),
        content: TextField(
          controller: controller,
          autofocus: true,
          minLines: 3,
          maxLines: 6,
          maxLength: 2000,
          decoration: const InputDecoration(
            labelText: 'What happened?',
            alignLabelWithHint: true,
          ),
        ),
        actions: <Widget>[
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Keep gig')),
          FilledButton(
            onPressed: () => Navigator.pop(context, controller.text.trim()),
            child: const Text('Submit dispute'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (reason == null || reason.isEmpty || !mounted) return;
    try {
      await context.read<KarmaRepository>().dispute(gigId: gig.id, reason: reason);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Dispute opened. The trust team will review it.')),
      );
    } on Object catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(errorMessage(error))),
        );
      }
    }
  }

  Future<bool> _confirm({
    required String title,
    required String message,
    required String action,
    bool destructive = true,
  }) async =>
      await showDialog<bool>(
        context: context,
        builder: (BuildContext context) => AlertDialog(
          title: Text(title),
          content: Text(message),
          actions: <Widget>[
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Back')),
            FilledButton(
              style: destructive
                  ? FilledButton.styleFrom(backgroundColor: AppColors.rose)
                  : null,
              onPressed: () => Navigator.pop(context, true),
              child: Text(action),
            ),
          ],
        ),
      ) ??
      false;

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final bool canWork = context.watch<SessionController>().user?.can('can_work') ?? false;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        key: const PageStorageKey<String>('gigs'),
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
                  Row(
                    children: <Widget>[
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            Text('Your work', style: Theme.of(context).textTheme.headlineSmall),
                            const Text(
                              'Every gig, from match to proof.',
                              style: TextStyle(color: AppColors.textMuted),
                            ),
                          ],
                        ),
                      ),
                      if (canWork)
                        SegmentedButton<String>(
                          showSelectedIcon: false,
                          segments: const <ButtonSegment<String>>[
                            ButtonSegment<String>(value: 'customer', label: Text('Hiring')),
                            ButtonSegment<String>(value: 'worker', label: Text('Working')),
                          ],
                          selected: <String>{_role},
                          onSelectionChanged: (Set<String> selected) {
                            _live?.close();
                            setState(() {
                              _role = selected.first;
                              _gigs = null;
                              _live = null;
                              _subscribedGig = null;
                              _liveState = LiveConnectionState.paused;
                            });
                            _load();
                          },
                        ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  if (_stats != null) _StatsCard(stats: _stats!),
                  if (_error != null) ...<Widget>[
                    const SizedBox(height: 12),
                    ErrorPanel(message: errorMessage(_error!), onRetry: _load),
                  ],
                  const SizedBox(height: 14),
                  if (_gigs == null)
                    _error == null
                        ? const LoadingCards(count: 2)
                        : const SizedBox.shrink()
                  else if (_gigs!.isEmpty)
                    EmptyState(
                      icon: Icons.work_outline_rounded,
                      title: _role == 'worker' ? 'No assigned work' : 'No gigs yet',
                      message: _role == 'worker'
                          ? 'Go online in your profile so nearby customers can find you.'
                          : 'Post a clear request and see explainable matches nearby.',
                      action: _role == 'customer'
                          ? FilledButton.icon(
                              onPressed: widget.onPostGig,
                              icon: const Icon(Icons.add_rounded),
                              label: const Text('Post a gig'),
                            )
                          : null,
                    )
                  else
                    ..._gigs!.map((Gig gig) {
                      final bool active = gig.isActive;
                      return Padding(
                        key: ValueKey<int>(gig.id),
                        padding: const EdgeInsets.only(bottom: 12),
                        child: _GigCard(
                          gig: gig,
                          isWorkerView: _role == 'worker',
                          liveState: active && gig.id == _subscribedGig ? _liveState : null,
                          busy: _busyGig == gig.id,
                          onAdvance: () => _advance(gig),
                          onSecurePayment: () => _securePayment(gig),
                          onReleasePayment: () => _releasePayment(gig),
                          onChat: () => _openBitchat(gig),
                          onSos: () => _sos(gig),
                          onCancel: () => _cancel(gig),
                          onDispute: () => _dispute(gig),
                          onReviewed: _load,
                        ),
                      );
                    }),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatsCard extends StatelessWidget {
  const _StatsCard({required this.stats});

  final GigStats stats;

  @override
  Widget build(BuildContext context) => KarmaCard(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
        child: Row(
          children: <Widget>[
            _Stat(label: 'Completed', value: '${stats.gigsCompleted}'),
            const _StatDivider(),
            _Stat(label: 'Wallet', value: inr(stats.walletBalance)),
            const _StatDivider(),
            _Stat(label: 'Lifetime', value: inr(stats.lifetimeEarned)),
          ],
        ),
      );
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Expanded(
        child: Column(
          children: <Widget>[
            Text(
              label.toUpperCase(),
              style: const TextStyle(
                color: AppColors.textFaint,
                fontSize: 9.5,
                fontWeight: FontWeight.w700,
                letterSpacing: 0.5,
              ),
            ),
            const SizedBox(height: 3),
            FittedBox(
              fit: BoxFit.scaleDown,
              child: Text(
                value,
                style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 17,
                  fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
                ),
              ),
            ),
          ],
        ),
      );
}

class _StatDivider extends StatelessWidget {
  const _StatDivider();

  @override
  Widget build(BuildContext context) => const SizedBox(
        height: 36,
        child: VerticalDivider(width: 20),
      );
}

class _GigCard extends StatelessWidget {
  const _GigCard({
    required this.gig,
    required this.isWorkerView,
    required this.busy,
    required this.onAdvance,
    required this.onSecurePayment,
    required this.onReleasePayment,
    required this.onChat,
    required this.onSos,
    required this.onCancel,
    required this.onDispute,
    required this.onReviewed,
    this.liveState,
  });

  final Gig gig;
  final bool isWorkerView;
  final bool busy;
  final LiveConnectionState? liveState;
  final VoidCallback onAdvance;
  final VoidCallback onSecurePayment;
  final VoidCallback onReleasePayment;
  final VoidCallback onChat;
  final VoidCallback onSos;
  final VoidCallback onCancel;
  final VoidCallback onDispute;
  final VoidCallback onReviewed;

  @override
  Widget build(BuildContext context) => KarmaCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(gig.title, style: Theme.of(context).textTheme.titleMedium),
                      const SizedBox(height: 3),
                      Text(
                        '${gig.addressLabel.isEmpty ? 'Location unavailable' : gig.addressLabel} · #${gig.id}',
                        style: const TextStyle(color: AppColors.textFaint, fontSize: 12.5),
                      ),
                    ],
                  ),
                ),
                _StatusPill(status: gig.status),
                PopupMenuButton<String>(
                  tooltip: 'Gig actions',
                  onSelected: (String value) {
                    if (value == 'cancel') onCancel();
                    if (value == 'dispute') onDispute();
                  },
                  itemBuilder: (_) => <PopupMenuEntry<String>>[
                    if (gig.isActive && gig.status != 'completion_pending')
                      const PopupMenuItem<String>(
                        value: 'cancel',
                        child: Text('Cancel gig'),
                      ),
                    const PopupMenuItem<String>(
                      value: 'dispute',
                      child: Text('Open a dispute'),
                    ),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 11),
            Row(
              children: <Widget>[
                Text(
                  inr(gig.total),
                  style: const TextStyle(
                    fontSize: 19,
                    fontWeight: FontWeight.w800,
                    fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
                  ),
                ),
                if (gig.status != 'searching') ...<Widget>[
                  const SizedBox(width: 8),
                  _PaymentBadge(status: gig.paymentStatus),
                ],
                const Spacer(),
                if (liveState != null) _LiveBadge(state: liveState!),
              ],
            ),
            if (gig.status != 'searching' && gig.status != 'cancelled') ...<Widget>[
              const SizedBox(height: 16),
              _LifecycleRail(status: gig.status),
            ],
            if (gig.isActive) ...<Widget>[
              const SizedBox(height: 15),
              if (!isWorkerView &&
                  gig.status == 'assigned' &&
                  !_paymentIsSecured(gig.paymentStatus)) ...<Widget>[
                FilledButton.icon(
                  onPressed: busy ? null : onSecurePayment,
                  icon: const Icon(Icons.lock_rounded),
                  label: Text(busy ? 'Opening Stripe…' : 'Secure ${inr(gig.total)}'),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Stripe authorizes the fixed price now. Capture happens only after you approve the work.',
                  style: TextStyle(color: AppColors.textMuted, fontSize: 11.5),
                ),
                const SizedBox(height: 12),
              ],
              if (!isWorkerView && gig.status == 'completion_pending') ...<Widget>[
                FilledButton.icon(
                  onPressed: busy ? null : onReleasePayment,
                  icon: const Icon(Icons.verified_rounded),
                  label: Text(busy ? 'Releasing…' : 'Approve work & release payment'),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Review the proof first. Releasing captures the Stripe payment and pays the worker once.',
                  style: TextStyle(color: AppColors.textMuted, fontSize: 11.5),
                ),
                const SizedBox(height: 12),
              ],
              if (isWorkerView &&
                  gig.status == 'assigned' &&
                  !_paymentIsSecured(gig.paymentStatus)) ...<Widget>[
                const _PaymentNotice(
                  icon: Icons.hourglass_top_rounded,
                  text: 'Waiting for the customer to secure payment before travel begins.',
                ),
                const SizedBox(height: 9),
              ],
              if (isWorkerView && gig.status == 'completion_pending') ...<Widget>[
                const _PaymentNotice(
                  icon: Icons.task_alt_rounded,
                  text: 'Proof submitted. Payment remains secured while the customer reviews it.',
                ),
                const SizedBox(height: 9),
              ],
              if (isWorkerView &&
                  _nextLabel(gig.status) != null &&
                  (gig.status != 'assigned' || _paymentIsSecured(gig.paymentStatus))) ...<Widget>[
                FilledButton(
                  onPressed: busy ? null : onAdvance,
                  child: Text(busy ? 'Updating…' : _nextLabel(gig.status)!),
                ),
                const SizedBox(height: 9),
              ],
              Row(
                children: <Widget>[
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: onChat,
                      icon: const Icon(Icons.lock_outline_rounded, size: 18),
                      label: const Text('Bitchat'),
                    ),
                  ),
                  const SizedBox(width: 9),
                  Semantics(
                    label: 'Send emergency SOS now',
                    button: true,
                    child: FilledButton.icon(
                      onPressed: onSos,
                      style: FilledButton.styleFrom(
                        backgroundColor: AppColors.rose,
                        minimumSize: const Size(92, 50),
                        padding: const EdgeInsets.symmetric(horizontal: 14),
                      ),
                      icon: const Icon(Icons.sos_rounded),
                      label: const Text('SOS'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              const Row(
                children: <Widget>[
                  Icon(Icons.timer_outlined, size: 13, color: AppColors.textFaint),
                  SizedBox(width: 4),
                  Text(
                    'Encrypted messages burn automatically',
                    style: TextStyle(color: AppColors.textFaint, fontSize: 10.5),
                  ),
                ],
              ),
            ],
            if (!isWorkerView && gig.status == 'completed') ...<Widget>[
              const SizedBox(height: 14),
              _ReviewPanel(gigId: gig.id, onDone: onReviewed),
            ],
          ],
        ),
      );

  static String? _nextLabel(String status) => switch (status) {
        'assigned' => 'Start journey',
        'en_route' => 'Mark arrived',
        'arrived' => 'Start work',
        'in_progress' => 'Submit completion proof',
        _ => null,
      };

  static bool _paymentIsSecured(String status) =>
      status == 'authorized' || status == 'captured' || status == 'paid';
}

class _PaymentBadge extends StatelessWidget {
  const _PaymentBadge({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final (IconData, String, Color, Color) presentation = switch (status) {
      'authorized' => (
          Icons.lock_rounded,
          'Secured',
          AppColors.lime,
          AppColors.paleLime,
        ),
      'captured' => (
          Icons.account_balance_rounded,
          'Captured',
          AppColors.cyan,
          AppColors.paleCyan,
        ),
      'paid' => (
          Icons.check_circle_rounded,
          'Paid',
          AppColors.lime,
          AppColors.paleLime,
        ),
      'refunded' => (
          Icons.undo_rounded,
          'Refunded',
          AppColors.violet,
          AppColors.paleViolet,
        ),
      'processing' || 'requires_action' => (
          Icons.sync_rounded,
          'Processing',
          AppColors.cyan,
          AppColors.paleCyan,
        ),
      'cancelled' => (
          Icons.money_off_rounded,
          'Cancelled',
          AppColors.textFaint,
          AppColors.surfaceMuted,
        ),
      _ => (
          Icons.lock_open_rounded,
          'Payment required',
          AppColors.gold,
          AppColors.paleGold,
        ),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
      decoration: BoxDecoration(
        color: presentation.$4,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Icon(presentation.$1, size: 13, color: presentation.$3),
          const SizedBox(width: 4),
          Text(
            presentation.$2,
            style: TextStyle(
              color: presentation.$3,
              fontSize: 10.5,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

class _PaymentNotice extends StatelessWidget {
  const _PaymentNotice({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(11),
        decoration: BoxDecoration(
          color: AppColors.paleGold,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.line),
        ),
        child: Row(
          children: <Widget>[
            Icon(icon, size: 18, color: AppColors.gold),
            const SizedBox(width: 9),
            Expanded(
              child: Text(
                text,
                style: const TextStyle(color: AppColors.textMuted, fontSize: 12),
              ),
            ),
          ],
        ),
      );
}

class _LifecycleRail extends StatelessWidget {
  const _LifecycleRail({required this.status});

  final String status;
  static const List<String> _rail = <String>[
    'assigned',
    'en_route',
    'arrived',
    'in_progress',
    'completion_pending',
    'completed',
  ];

  @override
  Widget build(BuildContext context) {
    final int current = _rail.indexOf(status);
    return Semantics(
      label: 'Gig progress: ${titleCaseStatus(status)}',
      child: Row(
        children: _rail.indexed.map(((int, String) item) {
          final bool done = item.$1 <= current;
          return Expanded(
            flex: item.$1 == _rail.length - 1 ? 0 : 1,
            child: Row(
              children: <Widget>[
                Column(
                  children: <Widget>[
                    AnimatedContainer(
                      duration: AppTheme.quick,
                      width: 14,
                      height: 14,
                      decoration: BoxDecoration(
                        color: done ? AppColors.lime : AppColors.line,
                        shape: BoxShape.circle,
                        border: item.$1 == current
                            ? Border.all(color: const Color(0xFFD9ECC0), width: 3)
                            : null,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _shortLabel(item.$2),
                      style: TextStyle(
                        color: done ? AppColors.ink : AppColors.textFaint,
                        fontWeight: item.$1 == current ? FontWeight.w700 : FontWeight.w500,
                        fontSize: 9.5,
                      ),
                    ),
                  ],
                ),
                if (item.$1 < _rail.length - 1)
                  Expanded(
                    child: Container(
                      height: 2,
                      margin: const EdgeInsets.only(bottom: 17),
                      color: item.$1 < current ? AppColors.lime : AppColors.line,
                    ),
                  ),
              ],
            ),
          );
        }).toList(growable: false),
      ),
    );
  }

  static String _shortLabel(String status) => switch (status) {
        'en_route' => 'En route',
        'in_progress' => 'Working',
        'completion_pending' => 'Review',
        _ => titleCaseStatus(status),
      };
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final bool done = status == 'completed';
    final bool cancelled = status == 'cancelled';
    final Color color = done
        ? AppColors.lime
        : cancelled
            ? AppColors.textFaint
            : AppColors.cyan;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: done
            ? AppColors.paleLime
            : cancelled
                ? AppColors.surfaceMuted
                : AppColors.paleCyan,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        titleCaseStatus(status),
        style: TextStyle(color: color, fontSize: 11.5, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _LiveBadge extends StatelessWidget {
  const _LiveBadge({required this.state});

  final LiveConnectionState state;

  @override
  Widget build(BuildContext context) {
    final String label = switch (state) {
      LiveConnectionState.connecting => 'Connecting',
      LiveConnectionState.live => 'Live',
      LiveConnectionState.paused => 'Updates paused',
    };
    final Color color = switch (state) {
      LiveConnectionState.connecting => AppColors.cyan,
      LiveConnectionState.live => AppColors.lime,
      LiveConnectionState.paused => AppColors.textFaint,
    };
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Container(width: 7, height: 7, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
        const SizedBox(width: 5),
        Text(label, style: TextStyle(color: color, fontSize: 11.5, fontWeight: FontWeight.w700)),
      ],
    );
  }
}

class _ReviewPanel extends StatefulWidget {
  const _ReviewPanel({required this.gigId, required this.onDone});

  final int gigId;
  final VoidCallback onDone;

  @override
  State<_ReviewPanel> createState() => _ReviewPanelState();
}

class _ReviewPanelState extends State<_ReviewPanel> {
  final TextEditingController _comment = TextEditingController();
  int _rating = 5;
  bool _busy = false;
  bool _checking = true;
  bool _done = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _checkExistingReview();
  }

  Future<void> _checkExistingReview() async {
    try {
      final bool reviewed = await context
          .read<KarmaRepository>()
          .gigHasReview(widget.gigId);
      if (mounted) {
        setState(() {
          _done = reviewed;
          _checking = false;
        });
      }
    } on Object {
      // A failed preflight must not hide the review form. The POST endpoint
      // remains the final idempotency guard and will return a useful conflict.
      if (mounted) setState(() => _checking = false);
    }
  }

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<KarmaRepository>().reviewGig(
            gigId: widget.gigId,
            rating: _rating,
            comment: _comment.text,
          );
      HapticFeedback.mediumImpact();
      if (!mounted) return;
      setState(() => _done = true);
      widget.onDone();
      try {
        await context.read<SessionController>().refreshUser();
      } on Object {
        // The review is already posted. A profile refresh can be retried by
        // normal screen refresh and must not turn this into a failed action.
      }
    } on Object catch (error) {
      if (mounted) setState(() => _error = errorMessage(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_checking) {
      return const SizedBox(
        height: 48,
        child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
      );
    }
    if (_done) {
      return const Row(
        children: <Widget>[
          Icon(Icons.check_circle, color: AppColors.lime, size: 19),
          SizedBox(width: 7),
          Text(
            'Review posted · their Karma just moved',
            style: TextStyle(color: AppColors.lime, fontWeight: FontWeight.w700),
          ),
        ],
      );
    }
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceMuted,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          const Text('Rate this work', style: TextStyle(fontWeight: FontWeight.w700)),
          Semantics(
            label: '$_rating out of 5 stars',
            child: Row(
              children: List<Widget>.generate(5, (int index) {
                final int value = index + 1;
                return IconButton(
                  tooltip: '$value star${value == 1 ? '' : 's'}',
                  visualDensity: VisualDensity.compact,
                  onPressed: () => setState(() => _rating = value),
                  icon: Icon(
                    Icons.star_rounded,
                    color: value <= _rating ? AppColors.gold : AppColors.lineStrong,
                  ),
                );
              }),
            ),
          ),
          TextField(
            controller: _comment,
            maxLength: 2000,
            decoration: const InputDecoration(
              hintText: 'What went well?',
              counterText: '',
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 7),
              child: Text(_error!, style: const TextStyle(color: AppColors.rose)),
            ),
          const SizedBox(height: 8),
          OutlinedButton(
            onPressed: _busy ? null : _submit,
            child: Text(_busy ? 'Posting…' : 'Post review'),
          ),
        ],
      ),
    );
  }
}

class _ProofSubmissionSheet extends StatefulWidget {
  const _ProofSubmissionSheet();

  @override
  State<_ProofSubmissionSheet> createState() => _ProofSubmissionSheetState();
}

class _ProofSubmissionSheetState extends State<_ProofSubmissionSheet> {
  final DeviceCapabilitiesService _device = DeviceCapabilitiesService();
  PendingImage? _before;
  PendingImage? _after;
  String? _beforeUrl;
  String? _afterUrl;
  bool _busy = false;
  String? _error;

  Future<void> _pick({required bool before}) async {
    try {
      final PendingImage? image = await _device.pickImage(context);
      if (image == null || !mounted) return;
      setState(() {
        if (before) {
          _before = image;
          _beforeUrl = null;
        } else {
          _after = image;
          _afterUrl = null;
        }
        _error = null;
      });
    } on Object catch (error) {
      if (mounted) setState(() => _error = errorMessage(error));
    }
  }

  Future<void> _complete() async {
    if (_before == null || _after == null) {
      setState(() => _error = 'Add both the before and after photos.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final KarmaRepository repository = context.read<KarmaRepository>();
      if (_beforeUrl == null) {
        final UploadedMedia before = await repository.uploadMedia(
          bytes: _before!.bytes,
          filename: _before!.name,
          purpose: 'proof_before',
        );
        _beforeUrl = before.url;
      }
      if (_afterUrl == null) {
        final UploadedMedia after = await repository.uploadMedia(
          bytes: _after!.bytes,
          filename: _after!.name,
          purpose: 'proof_after',
        );
        _afterUrl = after.url;
      }
      if (mounted) Navigator.pop(context, <String>[_beforeUrl!, _afterUrl!]);
    } on Object catch (error) {
      if (mounted) setState(() => _error = errorMessage(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(
          20,
          4,
          20,
          MediaQuery.viewInsetsOf(context).bottom + 24,
        ),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text('Submit completion proof', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 5),
              const Text(
                'Choose one before and one after image. KARMA uploads validated image bytes; external links are not accepted.',
                style: TextStyle(color: AppColors.textMuted),
              ),
              const SizedBox(height: 16),
              _ProofPicker(
                label: 'Before',
                image: _before,
                enabled: !_busy,
                onPick: () => _pick(before: true),
              ),
              const SizedBox(height: 11),
              _ProofPicker(
                label: 'After',
                image: _after,
                enabled: !_busy,
                onPick: () => _pick(before: false),
              ),
              if (_error != null) ...<Widget>[
                const SizedBox(height: 9),
                Text(_error!, style: const TextStyle(color: AppColors.rose)),
              ],
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: _busy ? null : _complete,
                icon: _busy
                    ? const SizedBox.square(
                        dimension: 18,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : const Icon(Icons.cloud_upload_outlined),
                label: Text(_busy ? 'Uploading proof…' : 'Submit proof for approval'),
              ),
            ],
          ),
        ),
      );
}

class _ProofPicker extends StatelessWidget {
  const _ProofPicker({
    required this.label,
    required this.image,
    required this.enabled,
    required this.onPick,
  });

  final String label;
  final PendingImage? image;
  final bool enabled;
  final VoidCallback onPick;

  @override
  Widget build(BuildContext context) => OutlinedButton(
        onPressed: enabled ? onPick : null,
        style: OutlinedButton.styleFrom(padding: const EdgeInsets.all(10)),
        child: Row(
          children: <Widget>[
            ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: SizedBox.square(
                dimension: 68,
                child: image == null
                    ? const ColoredBox(
                        color: AppColors.surfaceMuted,
                        child: Icon(Icons.add_a_photo_outlined),
                      )
                    : Image.memory(image!.bytes, fit: BoxFit.cover),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text('$label photo', style: const TextStyle(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 2),
                  Text(
                    image == null ? 'Take or choose an image' : 'Tap to replace',
                    style: const TextStyle(color: AppColors.textMuted, fontSize: 12),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
}
