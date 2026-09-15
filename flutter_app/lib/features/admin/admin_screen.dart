import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../data/models/models.dart';
import '../../data/repositories/karma_repository.dart';
import '../../shared/widgets/primitives.dart';
import '../auth/session_controller.dart';

enum _AdminSection { overview, verifications, safety }
enum _SafetyQueue { incidents, disputes }

class AdminScreen extends StatefulWidget {
  const AdminScreen({super.key});

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> {
  AdminAnalytics? _analytics;
  List<AdminVerification>? _verifications;
  List<AdminSafetyIncident>? _incidents;
  List<AdminDispute>? _disputes;
  Object? _error;
  bool _loading = false;
  int _revision = 0;
  _AdminSection _section = _AdminSection.overview;
  _SafetyQueue _safetyQueue = _SafetyQueue.incidents;
  final Set<String> _busyRecords = <String>{};

  bool get _isAdmin =>
      context.read<SessionController>().user?.can('admin') ?? false;

  @override
  void initState() {
    super.initState();
    if (_isAdmin) _load();
  }

  Future<void> _load() async {
    final int revision = ++_revision;
    setState(() {
      _loading = true;
      _error = null;
    });
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
      capture<AdminAnalytics>(repository.adminAnalytics()),
      capture<List<AdminVerification>>(repository.adminVerifications()),
      capture<List<AdminSafetyIncident>>(repository.adminSafetyIncidents()),
      capture<List<AdminDispute>>(repository.adminDisputes()),
    ]);
    if (!mounted || revision != _revision) return;
    setState(() {
      if (results[0] != null) _analytics = results[0]! as AdminAnalytics;
      if (results[1] != null) {
        _verifications = results[1]! as List<AdminVerification>;
      }
      if (results[2] != null) {
        _incidents = results[2]! as List<AdminSafetyIncident>;
      }
      if (results[3] != null) {
        _disputes = results[3]! as List<AdminDispute>;
      }
      _error = firstError;
      _loading = false;
    });
  }

  Future<void> _reviewVerification(
    AdminVerification verification,
    String decision,
  ) async {
    final String? note = await showDialog<String>(
      context: context,
      builder: (BuildContext context) => _VerificationDecisionDialog(
        verification: verification,
        decision: decision,
      ),
    );
    if (note == null || !mounted) return;
    final String key = 'verification:${verification.id}';
    setState(() => _busyRecords.add(key));
    try {
      await context.read<KarmaRepository>().reviewVerification(
            submissionId: verification.id,
            decision: decision,
            note: note,
          );
      if (!mounted) return;
      setState(() {
        _verifications = _verifications
            ?.where((AdminVerification item) => item.id != verification.id)
            .toList(growable: false);
      });
      _notice(
        decision == 'approved'
            ? '${verification.displayName} is verified.'
            : '${verification.displayName}\'s submission was rejected.',
      );
      await _load();
    } on Object catch (error) {
      if (mounted) _notice(errorMessage(error), error: true);
    } finally {
      if (mounted) setState(() => _busyRecords.remove(key));
    }
  }

  Future<void> _updateIncident(
    AdminSafetyIncident incident,
    String status,
  ) async {
    if (!await _confirmCaseChange('incident', status) || !mounted) return;
    final String key = 'incident:${incident.id}';
    setState(() => _busyRecords.add(key));
    try {
      await context
          .read<KarmaRepository>()
          .updateAdminIncident(incident.id, status);
      if (!mounted) return;
      setState(() {
        _incidents = _incidents
            ?.map(
              (AdminSafetyIncident item) =>
                  item.id == incident.id ? item.copyWith(status: status) : item,
            )
            .toList(growable: false);
      });
      _notice('Incident #${incident.id} marked ${_statusLabel(status)}.');
      await _load();
    } on Object catch (error) {
      if (mounted) _notice(errorMessage(error), error: true);
    } finally {
      if (mounted) setState(() => _busyRecords.remove(key));
    }
  }

  Future<void> _updateDispute(AdminDispute dispute, String status) async {
    if (!await _confirmCaseChange('dispute', status) || !mounted) return;
    final String key = 'dispute:${dispute.id}';
    setState(() => _busyRecords.add(key));
    try {
      await context
          .read<KarmaRepository>()
          .updateAdminDispute(dispute.id, status);
      if (!mounted) return;
      setState(() {
        _disputes = _disputes
            ?.map(
              (AdminDispute item) =>
                  item.id == dispute.id ? item.copyWith(status: status) : item,
            )
            .toList(growable: false);
      });
      _notice('Dispute #${dispute.id} marked ${_statusLabel(status)}.');
      await _load();
    } on Object catch (error) {
      if (mounted) _notice(errorMessage(error), error: true);
    } finally {
      if (mounted) setState(() => _busyRecords.remove(key));
    }
  }

  Future<bool> _confirmCaseChange(String kind, String status) async {
    if (status == 'in_review') return true;
    return await showDialog<bool>(
          context: context,
          builder: (BuildContext context) => AlertDialog(
            icon: Icon(
              status == 'resolved'
                  ? Icons.task_alt_rounded
                  : Icons.cancel_outlined,
              color: status == 'resolved' ? AppColors.lime : AppColors.rose,
            ),
            title: Text('${_statusLabel(status)} this $kind?'),
            content: Text(
              status == 'resolved'
                  ? 'This closes the case as handled. The decision is final.'
                  : 'This closes the case without action. The decision is final.',
            ),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('Keep open'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: Text(_statusLabel(status)),
              ),
            ],
          ),
        ) ??
        false;
  }

  void _copyLocation(AdminSafetyIncident incident) {
    final double? lat = incident.lat;
    final double? lng = incident.lng;
    if (lat == null || lng == null) return;
    Clipboard.setData(ClipboardData(text: '$lat,$lng'));
    _notice('Coordinates copied.');
  }

  void _notice(String message, {bool error = false}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: error ? AppColors.rose : AppColors.ink,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final User? user = context.watch<SessionController>().user;
    if (user == null || !user.can('admin')) {
      return Scaffold(
        appBar: AppBar(title: const Text('Admin console')),
        body: const ContentRail(
          child: EmptyState(
            icon: Icons.lock_outline_rounded,
            title: 'Restricted area',
            message: 'This console requires the separately provisioned admin capability.',
          ),
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Trust console'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Refresh admin data',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh_rounded),
          ),
          const SizedBox(width: 6),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 40),
          children: <Widget>[
            Align(
              alignment: Alignment.topCenter,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1040),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: <Widget>[
                    _AdminHeader(user: user),
                    if (_loading) ...<Widget>[
                      const SizedBox(height: 12),
                      const LinearProgressIndicator(minHeight: 3),
                    ],
                    if (_error != null) ...<Widget>[
                      const SizedBox(height: 12),
                      ErrorPanel(message: errorMessage(_error!), onRetry: _load),
                    ],
                    const SizedBox(height: 14),
                    SegmentedButton<_AdminSection>(
                      showSelectedIcon: false,
                      segments: const <ButtonSegment<_AdminSection>>[
                        ButtonSegment<_AdminSection>(
                          value: _AdminSection.overview,
                          label: Text('Overview'),
                        ),
                        ButtonSegment<_AdminSection>(
                          value: _AdminSection.verifications,
                          label: Text('KYC'),
                        ),
                        ButtonSegment<_AdminSection>(
                          value: _AdminSection.safety,
                          label: Text('Safety'),
                        ),
                      ],
                      selected: <_AdminSection>{_section},
                      onSelectionChanged: (Set<_AdminSection> selected) {
                        setState(() => _section = selected.first);
                      },
                    ),
                    const SizedBox(height: 14),
                    AnimatedSwitcher(
                      duration: AppTheme.enter,
                      child: switch (_section) {
                        _AdminSection.overview => _buildOverview(),
                        _AdminSection.verifications => _buildVerifications(user),
                        _AdminSection.safety => _buildSafety(),
                      },
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildOverview() {
    final AdminAnalytics? analytics = _analytics;
    if (analytics == null) {
      return const LoadingCards(key: ValueKey<String>('overview-loading'), count: 3);
    }
    final int activeIncidents = _incidents
            ?.where((AdminSafetyIncident item) => _isOpen(item.status))
            .length ??
        analytics.openIncidents;
    final int activeDisputes =
        _disputes?.where((AdminDispute item) => _isOpen(item.status)).length ??
            analytics.openDisputes;
    final int pendingKyc =
        _verifications?.length ?? analytics.pendingVerifications;

    return Column(
      key: const ValueKey<String>('overview'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        LayoutBuilder(
          builder: (BuildContext context, BoxConstraints constraints) {
            final int columns = constraints.maxWidth >= 760 ? 3 : 2;
            return GridView.count(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              crossAxisCount: columns,
              crossAxisSpacing: 10,
              mainAxisSpacing: 10,
              childAspectRatio: columns == 3 ? 1.9 : 1.45,
              children: <Widget>[
                _MetricCard(
                  label: 'People',
                  value: analytics.users,
                  icon: Icons.groups_2_outlined,
                  color: AppColors.violet,
                ),
                _MetricCard(
                  label: 'Workers',
                  value: analytics.workers,
                  icon: Icons.engineering_outlined,
                  color: AppColors.lime,
                ),
                _MetricCard(
                  label: 'All gigs',
                  value: analytics.gigs,
                  icon: Icons.work_outline_rounded,
                  color: AppColors.cyan,
                ),
                _MetricCard(
                  label: 'Completed',
                  value: analytics.gigsCompleted,
                  icon: Icons.task_alt_rounded,
                  color: AppColors.lime,
                ),
                _MetricCard(
                  label: 'Posts',
                  value: analytics.posts,
                  icon: Icons.dynamic_feed_outlined,
                  color: AppColors.violet,
                ),
                _MetricCard(
                  label: 'Proof receipts',
                  value: analytics.proofPosts,
                  icon: Icons.verified_outlined,
                  color: AppColors.gold,
                ),
              ],
            );
          },
        ),
        const SizedBox(height: 12),
        KarmaCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              const SectionLabel('Proof integrity'),
              const SizedBox(height: 12),
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: <Widget>[
                  Text(
                    '${(analytics.proofRate * 100).round()}%',
                    style: Theme.of(context).textTheme.displaySmall?.copyWith(
                          color: AppColors.lime,
                          fontFeatures: const <FontFeature>[
                            FontFeature.tabularFigures(),
                          ],
                        ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.only(bottom: 5),
                      child: Text(
                        '${analytics.proofPostsFromGigs} of ${analytics.gigsCompleted} completed gigs published linked proof.',
                        style: const TextStyle(color: AppColors.textMuted),
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              ClipRRect(
                borderRadius: BorderRadius.circular(99),
                child: LinearProgressIndicator(
                  value: analytics.proofRate.clamp(0, 1).toDouble(),
                  minHeight: 9,
                  backgroundColor: AppColors.surfaceMuted,
                  color: AppColors.lime,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        const SectionLabel('Needs attention'),
        const SizedBox(height: 9),
        _QueueCard(
          icon: Icons.badge_outlined,
          color: AppColors.gold,
          title: 'Identity reviews',
          detail: '$pendingKyc waiting for a second pair of eyes',
          count: pendingKyc,
          onTap: () => setState(() => _section = _AdminSection.verifications),
        ),
        const SizedBox(height: 9),
        _QueueCard(
          icon: Icons.sos_outlined,
          color: AppColors.rose,
          title: 'Safety signals',
          detail: '$activeIncidents open or under review',
          count: activeIncidents,
          onTap: () => setState(() {
            _section = _AdminSection.safety;
            _safetyQueue = _SafetyQueue.incidents;
          }),
        ),
        const SizedBox(height: 9),
        _QueueCard(
          icon: Icons.gavel_outlined,
          color: AppColors.cyan,
          title: 'Disputes',
          detail: '$activeDisputes open or under review',
          count: activeDisputes,
          onTap: () => setState(() {
            _section = _AdminSection.safety;
            _safetyQueue = _SafetyQueue.disputes;
          }),
        ),
      ],
    );
  }

  Widget _buildVerifications(User admin) {
    final List<AdminVerification>? verifications = _verifications;
    if (verifications == null) {
      return const LoadingCards(
        key: ValueKey<String>('verifications-loading'),
        count: 2,
      );
    }
    if (verifications.isEmpty) {
      return const KarmaCard(
        key: ValueKey<String>('verifications-empty'),
        child: EmptyState(
          icon: Icons.verified_user_outlined,
          title: 'KYC queue is clear',
          message: 'New identity submissions will appear here for review.',
        ),
      );
    }
    return Column(
      key: const ValueKey<String>('verifications'),
      children: verifications.map((AdminVerification verification) {
        final String key = 'verification:${verification.id}';
        return Padding(
          key: ValueKey<int>(verification.id),
          padding: const EdgeInsets.only(bottom: 10),
          child: _VerificationCard(
            verification: verification,
            isSelf: verification.userId == admin.id,
            busy: _busyRecords.contains(key),
            onApprove: () => _reviewVerification(verification, 'approved'),
            onReject: () => _reviewVerification(verification, 'rejected'),
          ),
        );
      }).toList(growable: false),
    );
  }

  Widget _buildSafety() => Column(
        key: const ValueKey<String>('safety'),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          SegmentedButton<_SafetyQueue>(
            showSelectedIcon: false,
            segments: const <ButtonSegment<_SafetyQueue>>[
              ButtonSegment<_SafetyQueue>(
                value: _SafetyQueue.incidents,
                icon: Icon(Icons.sos_outlined),
                label: Text('Signals'),
              ),
              ButtonSegment<_SafetyQueue>(
                value: _SafetyQueue.disputes,
                icon: Icon(Icons.gavel_outlined),
                label: Text('Disputes'),
              ),
            ],
            selected: <_SafetyQueue>{_safetyQueue},
            onSelectionChanged: (Set<_SafetyQueue> selected) {
              setState(() => _safetyQueue = selected.first);
            },
          ),
          const SizedBox(height: 12),
          if (_safetyQueue == _SafetyQueue.incidents)
            _buildIncidents()
          else
            _buildDisputes(),
        ],
      );

  Widget _buildIncidents() {
    final List<AdminSafetyIncident>? incidents = _incidents;
    if (incidents == null) return const LoadingCards(count: 2);
    if (incidents.isEmpty) {
      return const KarmaCard(
        child: EmptyState(
          icon: Icons.health_and_safety_outlined,
          title: 'No safety signals',
          message: 'Emergency alerts will appear here immediately.',
        ),
      );
    }
    return Column(
      children: incidents.map((AdminSafetyIncident incident) {
        final String key = 'incident:${incident.id}';
        return Padding(
          key: ValueKey<int>(incident.id),
          padding: const EdgeInsets.only(bottom: 10),
          child: _IncidentCard(
            incident: incident,
            busy: _busyRecords.contains(key),
            onCopyLocation: () => _copyLocation(incident),
            onStatus: (String status) => _updateIncident(incident, status),
          ),
        );
      }).toList(growable: false),
    );
  }

  Widget _buildDisputes() {
    final List<AdminDispute>? disputes = _disputes;
    if (disputes == null) return const LoadingCards(count: 2);
    if (disputes.isEmpty) {
      return const KarmaCard(
        child: EmptyState(
          icon: Icons.handshake_outlined,
          title: 'No disputes',
          message: 'Work disagreements will be queued here for review.',
        ),
      );
    }
    return Column(
      children: disputes.map((AdminDispute dispute) {
        final String key = 'dispute:${dispute.id}';
        return Padding(
          key: ValueKey<int>(dispute.id),
          padding: const EdgeInsets.only(bottom: 10),
          child: _DisputeCard(
            dispute: dispute,
            busy: _busyRecords.contains(key),
            onStatus: (String status) => _updateDispute(dispute, status),
          ),
        );
      }).toList(growable: false),
    );
  }

  static bool _isOpen(String status) =>
      status == 'open' || status == 'in_review';

  static String _statusLabel(String status) {
    final String label = status.replaceAll('_', ' ');
    return '${label[0].toUpperCase()}${label.substring(1)}';
  }
}

class _AdminHeader extends StatelessWidget {
  const _AdminHeader({required this.user});

  final User user;

  @override
  Widget build(BuildContext context) => KarmaCard(
        color: AppColors.ink,
        child: Row(
          children: <Widget>[
            Container(
              width: 52,
              height: 52,
              decoration: const BoxDecoration(
                color: Color(0xFF23183A),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.admin_panel_settings_outlined,
                color: Color(0xFFC4B5FD),
                size: 29,
              ),
            ),
            const SizedBox(width: 13),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  const Text(
                    'Trust & safety command',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 18,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    '${user.displayName} · privileged actions are server-gated',
                    style: const TextStyle(
                      color: Color(0xFFB8B5AE),
                      fontSize: 12.5,
                    ),
                  ),
                ],
              ),
            ),
            const Icon(Icons.lock_rounded, color: AppColors.gold, size: 19),
          ],
        ),
      );
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({
    required this.label,
    required this.value,
    required this.icon,
    required this.color,
  });

  final String label;
  final int value;
  final IconData icon;
  final Color color;

  @override
  Widget build(BuildContext context) => KarmaCard(
        padding: const EdgeInsets.all(14),
        child: Row(
          children: <Widget>[
            Container(
              width: 38,
              height: 38,
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(11),
              ),
              child: Icon(icon, color: color, size: 21),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerLeft,
                    child: Text(
                      '$value',
                      style: const TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.w800,
                        fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
                      ),
                    ),
                  ),
                  Text(
                    label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 11.5,
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

class _QueueCard extends StatelessWidget {
  const _QueueCard({
    required this.icon,
    required this.color,
    required this.title,
    required this.detail,
    required this.count,
    required this.onTap,
  });

  final IconData icon;
  final Color color;
  final String title;
  final String detail;
  final int count;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => KarmaCard(
        onTap: onTap,
        padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 13),
        child: Row(
          children: <Widget>[
            Icon(icon, color: color, size: 24),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
                  Text(
                    detail,
                    style: const TextStyle(color: AppColors.textMuted, fontSize: 12),
                  ),
                ],
              ),
            ),
            Container(
              constraints: const BoxConstraints(minWidth: 32),
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
              decoration: BoxDecoration(
                color: count > 0 ? color.withValues(alpha: 0.1) : AppColors.surfaceMuted,
                borderRadius: BorderRadius.circular(99),
              ),
              child: Text(
                '$count',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: count > 0 ? color : AppColors.textFaint,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            const SizedBox(width: 5),
            const Icon(Icons.chevron_right_rounded, color: AppColors.textFaint),
          ],
        ),
      );
}

class _VerificationCard extends StatelessWidget {
  const _VerificationCard({
    required this.verification,
    required this.isSelf,
    required this.busy,
    required this.onApprove,
    required this.onReject,
  });

  final AdminVerification verification;
  final bool isSelf;
  final bool busy;
  final VoidCallback onApprove;
  final VoidCallback onReject;

  @override
  Widget build(BuildContext context) {
    final String tier = switch (verification.documentType) {
      'aadhaar' => 'gold',
      'pan' => 'silver',
      _ => 'bronze',
    };
    return KarmaCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Row(
            children: <Widget>[
              UserAvatar(name: verification.displayName, radius: 21),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      verification.displayName,
                      style: const TextStyle(fontWeight: FontWeight.w800),
                    ),
                    Text(
                      '@${verification.handle} · ${compactDate(verification.createdAt)}',
                      style: const TextStyle(color: AppColors.textFaint, fontSize: 12),
                    ),
                  ],
                ),
              ),
              TierBadge(tier: tier),
            ],
          ),
          const SizedBox(height: 13),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppColors.surfaceMuted,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              children: <Widget>[
                const Icon(Icons.shield_outlined, color: AppColors.gold, size: 21),
                const SizedBox(width: 9),
                Expanded(
                  child: Text(
                    '${verification.documentType.toUpperCase()} · ${verification.documentRef}',
                    style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      letterSpacing: 0.2,
                    ),
                  ),
                ),
                const Text(
                  'MASKED',
                  style: TextStyle(
                    color: AppColors.textFaint,
                    fontSize: 9,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 0.7,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 13),
          if (isSelf)
            const Text(
              'A second administrator must review your own submission.',
              textAlign: TextAlign.center,
              style: TextStyle(color: AppColors.gold, fontWeight: FontWeight.w600),
            )
          else
            Row(
              children: <Widget>[
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: busy ? null : onReject,
                    icon: const Icon(Icons.close_rounded, color: AppColors.rose),
                    label: const Text('Reject'),
                  ),
                ),
                const SizedBox(width: 9),
                Expanded(
                  child: FilledButton.icon(
                    onPressed: busy ? null : onApprove,
                    style: FilledButton.styleFrom(backgroundColor: AppColors.lime),
                    icon: busy
                        ? const SizedBox.square(
                            dimension: 16,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.check_rounded),
                    label: Text(busy ? 'Saving…' : 'Approve'),
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }
}

class _IncidentCard extends StatelessWidget {
  const _IncidentCard({
    required this.incident,
    required this.busy,
    required this.onCopyLocation,
    required this.onStatus,
  });

  final AdminSafetyIncident incident;
  final bool busy;
  final VoidCallback onCopyLocation;
  final ValueChanged<String> onStatus;

  @override
  Widget build(BuildContext context) {
    final String name = incident.raisedByName.isEmpty
        ? 'User #${incident.raisedBy}'
        : incident.raisedByName;
    return KarmaCard(
      color: incident.status == 'open' ? const Color(0xFFFFF7F8) : AppColors.surface,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Container(
                width: 42,
                height: 42,
                decoration: const BoxDecoration(
                  color: Color(0xFFFFE4E9),
                  shape: BoxShape.circle,
                ),
                child: const Icon(Icons.sos_rounded, color: AppColors.rose),
              ),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      '$name raised an emergency',
                      style: const TextStyle(fontWeight: FontWeight.w800),
                    ),
                    Text(
                      'Incident #${incident.id}${incident.gigId == null ? '' : ' · Gig #${incident.gigId}'} · ${relativeTime(incident.createdAt)}',
                      style: const TextStyle(color: AppColors.textFaint, fontSize: 12),
                    ),
                  ],
                ),
              ),
              _StatusBadge(status: incident.status),
            ],
          ),
          if (incident.note.isNotEmpty) ...<Widget>[
            const SizedBox(height: 12),
            Text(incident.note),
          ],
          if (incident.againstUserId != null) ...<Widget>[
            const SizedBox(height: 8),
            Text(
              'Against ${incident.againstUserName?.isNotEmpty == true ? incident.againstUserName : 'user #${incident.againstUserId}'}',
              style: const TextStyle(color: AppColors.textMuted, fontSize: 12.5),
            ),
          ],
          if (incident.lat != null && incident.lng != null) ...<Widget>[
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                onPressed: onCopyLocation,
                icon: const Icon(Icons.location_on_outlined),
                label: Text(
                  '${incident.lat!.toStringAsFixed(4)}, ${incident.lng!.toStringAsFixed(4)}',
                ),
              ),
            ),
          ],
          _CaseActions(
            status: incident.status,
            busy: busy,
            onStatus: onStatus,
          ),
        ],
      ),
    );
  }
}

class _DisputeCard extends StatelessWidget {
  const _DisputeCard({
    required this.dispute,
    required this.busy,
    required this.onStatus,
  });

  final AdminDispute dispute;
  final bool busy;
  final ValueChanged<String> onStatus;

  @override
  Widget build(BuildContext context) {
    final String name = dispute.raisedByName.isEmpty
        ? 'User #${dispute.raisedBy}'
        : dispute.raisedByName;
    return KarmaCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const Icon(Icons.gavel_outlined, color: AppColors.cyan, size: 25),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      dispute.gigTitle.isEmpty
                          ? 'Gig #${dispute.gigId}'
                          : dispute.gigTitle,
                      style: const TextStyle(fontWeight: FontWeight.w800),
                    ),
                    Text(
                      '$name · @${dispute.raisedByHandle} · ${relativeTime(dispute.createdAt)}',
                      style: const TextStyle(color: AppColors.textFaint, fontSize: 12),
                    ),
                  ],
                ),
              ),
              _StatusBadge(status: dispute.status),
            ],
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppColors.surfaceMuted,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(dispute.reason),
          ),
          _CaseActions(
            status: dispute.status,
            busy: busy,
            onStatus: onStatus,
          ),
        ],
      ),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final Color color = switch (status) {
      'open' => AppColors.rose,
      'in_review' => AppColors.gold,
      'resolved' => AppColors.lime,
      _ => AppColors.textFaint,
    };
    final String label = status.replaceAll('_', ' ');
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Text(
        label.toUpperCase(),
        style: TextStyle(
          color: color,
          fontSize: 9.5,
          fontWeight: FontWeight.w800,
          letterSpacing: 0.4,
        ),
      ),
    );
  }
}

class _CaseActions extends StatelessWidget {
  const _CaseActions({
    required this.status,
    required this.busy,
    required this.onStatus,
  });

  final String status;
  final bool busy;
  final ValueChanged<String> onStatus;

  @override
  Widget build(BuildContext context) {
    if (status == 'resolved' || status == 'dismissed') {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(top: 13),
      child: Row(
        children: <Widget>[
          if (status == 'open') ...<Widget>[
            Expanded(
              child: OutlinedButton(
                onPressed: busy ? null : () => onStatus('in_review'),
                child: const Text('Take case'),
              ),
            ),
            const SizedBox(width: 8),
          ],
          Expanded(
            child: FilledButton.icon(
              onPressed: busy ? null : () => onStatus('resolved'),
              style: FilledButton.styleFrom(backgroundColor: AppColors.lime),
              icon: const Icon(Icons.task_alt_rounded),
              label: Text(busy ? 'Saving…' : 'Resolve'),
            ),
          ),
          const SizedBox(width: 5),
          IconButton(
            tooltip: 'Dismiss case',
            onPressed: busy ? null : () => onStatus('dismissed'),
            icon: const Icon(Icons.cancel_outlined, color: AppColors.textFaint),
          ),
        ],
      ),
    );
  }
}

class _VerificationDecisionDialog extends StatefulWidget {
  const _VerificationDecisionDialog({
    required this.verification,
    required this.decision,
  });

  final AdminVerification verification;
  final String decision;

  @override
  State<_VerificationDecisionDialog> createState() =>
      _VerificationDecisionDialogState();
}

class _VerificationDecisionDialogState
    extends State<_VerificationDecisionDialog> {
  final TextEditingController _note = TextEditingController();
  String? _error;

  bool get _approving => widget.decision == 'approved';

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  void _submit() {
    if (!_approving && _note.text.trim().isEmpty) {
      setState(() => _error = 'Add a reason the applicant can act on.');
      return;
    }
    Navigator.pop(context, _note.text.trim());
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        icon: Icon(
          _approving ? Icons.verified_user_outlined : Icons.person_off_outlined,
          color: _approving ? AppColors.lime : AppColors.rose,
        ),
        title: Text(
          _approving
              ? 'Approve ${widget.verification.displayName}?'
              : 'Reject this submission?',
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Text(
              _approving
                  ? 'This verifies their identity and unlocks worker onboarding. The Karma event cannot be undone.'
                  : 'The applicant may submit a new document after this final decision.',
              style: const TextStyle(color: AppColors.textMuted),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _note,
              autofocus: !_approving,
              maxLength: 500,
              minLines: 2,
              maxLines: 4,
              decoration: InputDecoration(
                labelText: _approving ? 'Reviewer note · optional' : 'Rejection reason',
                errorText: _error,
                alignLabelWithHint: true,
              ),
            ),
          ],
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: _submit,
            style: FilledButton.styleFrom(
              backgroundColor: _approving ? AppColors.lime : AppColors.rose,
            ),
            child: Text(_approving ? 'Approve identity' : 'Reject'),
          ),
        ],
      );
}
