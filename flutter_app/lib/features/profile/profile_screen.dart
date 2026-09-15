import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../data/models/models.dart';
import '../../data/repositories/karma_repository.dart';
import '../../data/services/device_capabilities_service.dart';
import '../../shared/widgets/primitives.dart';
import '../auth/session_controller.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key, this.refreshSignal = 0});

  final int refreshSignal;

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen>
    with AutomaticKeepAliveClientMixin<ProfileScreen> {
  final DeviceCapabilitiesService _device = DeviceCapabilitiesService();
  WorkerProfile? _worker;
  List<ServiceCategory>? _categories;
  List<VerificationSubmission>? _verifications;
  List<TrustedContact>? _contacts;
  Object? _error;
  bool _busy = false;
  int _loadRevision = 0;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(ProfileScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.refreshSignal != widget.refreshSignal) _load();
  }

  Future<void> _load() async {
    final int revision = ++_loadRevision;
    setState(() => _error = null);
    final KarmaRepository repository = context.read<KarmaRepository>();
    final SessionController session = context.read<SessionController>();
    User? user = session.user;
    Object? firstError;

    Future<T?> capture<T>(Future<T> request) async {
      try {
        return await request;
      } on Object catch (error) {
        firstError ??= error;
        return null;
      }
    }

    final User? refreshedUser = await capture<User>(repository.currentUser());
    if (!mounted || revision != _loadRevision) return;
    if (refreshedUser != null) {
      user = refreshedUser;
      await session.replaceUser(refreshedUser);
    }

    final List<Object?> results = await Future.wait<Object?>(<Future<Object?>>[
      capture<List<ServiceCategory>>(repository.categories()),
      capture<List<VerificationSubmission>>(repository.verifications()),
      capture<List<TrustedContact>>(repository.trustedContacts()),
      if (user?.can('can_work') ?? false)
        // The public profile includes proof history while the compact /me
        // response does not; it is still the current user's own public data.
        capture<WorkerProfile>(repository.workerProfile(publicUserId: user!.id))
      else
        Future<Object?>.value(),
    ]);
    if (!mounted || revision != _loadRevision) return;
    setState(() {
      if (results[0] != null) {
        _categories = results[0]! as List<ServiceCategory>;
      }
      if (results[1] != null) {
        _verifications = results[1]! as List<VerificationSubmission>;
      }
      if (results[2] != null) {
        _contacts = results[2]! as List<TrustedContact>;
      }
      if (results[3] != null) _worker = results[3]! as WorkerProfile;
      _error = firstError;
    });
  }

  Future<void> _enableHiring() async {
    setState(() => _busy = true);
    try {
      final User user = await context
          .read<KarmaRepository>()
          .grantCapability('can_hire');
      await context.read<SessionController>().replaceUser(user);
      if (!mounted) return;
      _notice('Hiring enabled. You can now post gigs.');
    } on Object catch (error) {
      if (mounted) _notice(errorMessage(error), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _toggleAvailability() async {
    final WorkerProfile? worker = _worker;
    if (worker == null) return;
    final bool goingOnline = !worker.isAvailable;
    SelectedLocation? location;
    if (goingOnline) {
      final bool consented = await confirmLocationConsent(
        context,
        title: 'Share location while online?',
        action: 'Share once & go online',
        includesGeocoder: false,
      );
      if (!consented || !mounted) return;
      try {
        final Position position = await _device.currentPosition();
        if (!mounted) return;
        location = SelectedLocation(
          lat: position.latitude,
          lng: position.longitude,
          label: 'Current worker location',
          source: 'device',
          consent: true,
          accuracyM: position.accuracy,
        );
      } on Object catch (error) {
        if (mounted) _notice(errorMessage(error), error: true);
        return;
      }
    }
    setState(() => _busy = true);
    try {
      await context.read<KarmaRepository>().setAvailability(
            available: goingOnline,
            location: location,
          );
      HapticFeedback.selectionClick();
      await _load();
      if (mounted) {
        _notice(
          worker.isAvailable
              ? 'You are offline. KARMA will not request location.'
              : 'You are online at the location you just shared.',
        );
      }
    } on Object catch (error) {
      if (mounted) _notice(errorMessage(error), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _addContact() async {
    final TrustedContact? contact = await showDialog<TrustedContact>(
      context: context,
      builder: (BuildContext context) => const _ContactDialog(),
    );
    if (contact != null && mounted) {
      setState(() => _contacts = <TrustedContact>[...?_contacts, contact]);
      _notice('${contact.name} added to your safety circle.');
    }
  }

  Future<void> _removeContact(TrustedContact contact) async {
    final bool remove = await showDialog<bool>(
          context: context,
          builder: (BuildContext context) => AlertDialog(
            title: Text('Remove ${contact.name}?'),
            content: const Text('They will no longer receive emergency alerts from KARMA.'),
            actions: <Widget>[
              TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
              FilledButton(
                style: FilledButton.styleFrom(backgroundColor: AppColors.rose),
                onPressed: () => Navigator.pop(context, true),
                child: const Text('Remove'),
              ),
            ],
          ),
        ) ??
        false;
    if (!remove || !mounted) return;
    try {
      await context.read<KarmaRepository>().removeTrustedContact(contact.id);
      if (mounted) {
        setState(() {
          _contacts = _contacts?.where((TrustedContact item) => item.id != contact.id).toList();
        });
      }
    } on Object catch (error) {
      if (mounted) _notice(errorMessage(error), error: true);
    }
  }

  Future<void> _logout() async {
    final bool confirmed = await showDialog<bool>(
          context: context,
          builder: (BuildContext context) => AlertDialog(
            title: const Text('Sign out?'),
            content: const Text('Your session will be removed securely from this device.'),
            actions: <Widget>[
              TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Stay')),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('Sign out'),
              ),
            ],
          ),
        ) ??
        false;
    if (confirmed && mounted) await context.read<SessionController>().logout();
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
    super.build(context);
    final User user = context.watch<SessionController>().user!;
    final VerificationSubmission? latest =
        (_verifications?.isEmpty ?? true) ? null : _verifications!.first;
    final bool approved =
        _verifications?.any((VerificationSubmission item) => item.status == 'approved') ?? false;

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        key: const PageStorageKey<String>('profile'),
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
                  _ProfileHero(user: user),
                  if (_error != null) ...<Widget>[
                    const SizedBox(height: 12),
                    ErrorPanel(message: errorMessage(_error!), onRetry: _load),
                  ],
                  const SizedBox(height: 12),
                  _CapabilitiesCard(
                    user: user,
                    busy: _busy,
                    onEnableHiring: _enableHiring,
                  ),
                  const SizedBox(height: 12),
                  if (user.can('can_work'))
                    _worker != null
                        ? _WorkerCard(
                            worker: _worker!,
                            busy: _busy,
                            onToggle: _toggleAvailability,
                          )
                        : KarmaCard(
                            child: Center(
                              child: _error == null
                                  ? const CircularProgressIndicator()
                                  : const Text(
                                      'Worker profile unavailable. Retry above.',
                                      style: TextStyle(color: AppColors.textMuted),
                                    ),
                            ),
                          )
                  else if (_verifications == null ||
                      (approved && _categories == null))
                    KarmaCard(
                      child: Center(
                        child: _error == null
                            ? const CircularProgressIndicator()
                            : const Text(
                                'Progression details unavailable. Retry above.',
                                style: TextStyle(color: AppColors.textMuted),
                              ),
                      ),
                    )
                  else if (approved)
                    _WorkerOnboardingCard(
                      categories: _categories!,
                      onDone: () async {
                        try {
                          await context.read<SessionController>().refreshUser();
                        } on Object catch (error) {
                          if (mounted) _notice(errorMessage(error), error: true);
                        }
                        if (mounted) await _load();
                      },
                    )
                  else
                    _VerificationCard(
                      latest: latest,
                      onSubmitted: _load,
                    ),
                  const SizedBox(height: 12),
                  _SafetyCard(
                    contacts: _contacts,
                    onAdd: _addContact,
                    onRemove: _removeContact,
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    onPressed: _logout,
                    icon: const Icon(Icons.logout_rounded),
                    label: const Text('Sign out securely'),
                  ),
                  const SizedBox(height: 10),
                  const Text(
                    'KARMA · Thou art the work you do.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: AppColors.textFaint, fontSize: 11.5),
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

class _ProfileHero extends StatelessWidget {
  const _ProfileHero({required this.user});

  final User user;

  @override
  Widget build(BuildContext context) => KarmaCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Stack(
                  alignment: Alignment.center,
                  children: <Widget>[
                    KarmaRing(value: user.karma, size: 82),
                    UserAvatar(name: user.displayName, url: user.avatarUrl, radius: 25),
                  ],
                ),
                const SizedBox(width: 15),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(user.displayName, style: Theme.of(context).textTheme.headlineSmall),
                      const SizedBox(height: 2),
                      Text(
                        '@${user.handle}${user.city == null ? '' : ' · ${user.city}'}',
                        style: const TextStyle(color: AppColors.textMuted),
                      ),
                      if (user.verificationTier != 'none') ...<Widget>[
                        const SizedBox(height: 7),
                        Align(
                          alignment: Alignment.centerLeft,
                          child: TierBadge(tier: user.verificationTier),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
            if (user.bio.isNotEmpty) ...<Widget>[
              const SizedBox(height: 14),
              Text(user.bio),
            ],
            const SizedBox(height: 16),
            Row(
              children: <Widget>[
                _ProfileStat(label: 'Posts', value: '${user.postsCount}'),
                _ProfileStat(label: 'Work karma', value: '${user.karmaWork}'),
                _ProfileStat(label: 'Social', value: '${user.karmaSocial}'),
                _ProfileStat(label: 'Streak', value: '${user.streak}d'),
              ],
            ),
          ],
        ),
      );
}

class _ProfileStat extends StatelessWidget {
  const _ProfileStat({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Expanded(
        child: Column(
          children: <Widget>[
            FittedBox(
              child: Text(
                value,
                style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 18,
                  fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
                ),
              ),
            ),
            Text(
              label,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textFaint, fontSize: 9.5),
            ),
          ],
        ),
      );
}

class _CapabilitiesCard extends StatelessWidget {
  const _CapabilitiesCard({
    required this.user,
    required this.busy,
    required this.onEnableHiring,
  });

  final User user;
  final bool busy;
  final VoidCallback onEnableHiring;

  @override
  Widget build(BuildContext context) => KarmaCard(
        child: Column(
          children: <Widget>[
            const SectionLabel('What you can do'),
            const SizedBox(height: 12),
            _Capability(
              title: 'Post and follow',
              detail: 'Share updates and celebrate useful work.',
              enabled: user.can('can_post'),
            ),
            const Divider(height: 22),
            _Capability(
              title: 'Hire professionals',
              detail: 'Post gigs and book verified people nearby.',
              enabled: user.can('can_hire'),
              action: user.can('can_hire')
                  ? null
                  : TextButton(
                      onPressed: busy ? null : onEnableHiring,
                      child: const Text('Enable'),
                    ),
            ),
            const Divider(height: 22),
            _Capability(
              title: 'Take work',
              detail: 'Requires identity review before entering a customer’s home.',
              enabled: user.can('can_work'),
              action: user.can('can_work')
                  ? null
                  : const Text(
                      'Needs KYC',
                      style: TextStyle(color: AppColors.textFaint, fontSize: 11.5),
                    ),
            ),
          ],
        ),
      );
}

class _Capability extends StatelessWidget {
  const _Capability({
    required this.title,
    required this.detail,
    required this.enabled,
    this.action,
  });

  final String title;
  final String detail;
  final bool enabled;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Row(
        children: <Widget>[
          Container(
            width: 25,
            height: 25,
            decoration: BoxDecoration(
              color: enabled ? AppColors.paleLime : AppColors.surfaceMuted,
              shape: BoxShape.circle,
              border: Border.all(color: enabled ? AppColors.lime : AppColors.lineStrong),
            ),
            child: Icon(
              enabled ? Icons.check_rounded : Icons.more_horiz_rounded,
              color: enabled ? AppColors.lime : AppColors.textFaint,
              size: 16,
            ),
          ),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
                Text(detail, style: const TextStyle(color: AppColors.textMuted, fontSize: 12)),
              ],
            ),
          ),
          if (action != null) action!,
        ],
      );
}

class _WorkerCard extends StatelessWidget {
  const _WorkerCard({
    required this.worker,
    required this.busy,
    required this.onToggle,
  });

  final WorkerProfile worker;
  final bool busy;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) => KarmaCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            const SectionLabel('Your work profile'),
            const SizedBox(height: 12),
            Row(
              children: <Widget>[
                _WorkMetric(label: 'Jobs done', value: '${worker.totalJobs}'),
                _WorkMetric(label: 'Rating', value: '★ ${worker.rating.toStringAsFixed(1)}'),
                _WorkMetric(label: 'Hourly', value: inr(worker.hourlyRate)),
              ],
            ),
            if (worker.category != null) ...<Widget>[
              const SizedBox(height: 12),
              Text(
                worker.category!,
                style: const TextStyle(color: AppColors.textMuted, fontWeight: FontWeight.w600),
              ),
            ],
            if (worker.skills.isNotEmpty) ...<Widget>[
              const SizedBox(height: 10),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: worker.skills
                    .map((String skill) => Chip(label: Text(skill), visualDensity: VisualDensity.compact))
                    .toList(growable: false),
              ),
            ],
            const SizedBox(height: 14),
            FilledButton.icon(
              onPressed: busy ? null : onToggle,
              style: FilledButton.styleFrom(
                backgroundColor: worker.isAvailable ? AppColors.lime : AppColors.ink,
              ),
              icon: Icon(worker.isAvailable ? Icons.radio_button_checked : Icons.circle_outlined),
              label: Text(
                busy
                    ? 'Updating…'
                    : worker.isAvailable
                        ? 'Online · visible nearby'
                        : 'Go online',
              ),
            ),
            const SizedBox(height: 8),
            Text(
              '${worker.proofs.length} proof post${worker.proofs.length == 1 ? '' : 's'} published from completed gigs.',
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textFaint, fontSize: 11.5),
            ),
          ],
        ),
      );
}

class _WorkMetric extends StatelessWidget {
  const _WorkMetric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Expanded(
        child: Column(
          children: <Widget>[
            FittedBox(
              child: Text(value, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 17)),
            ),
            Text(label, style: const TextStyle(color: AppColors.textFaint, fontSize: 10.5)),
          ],
        ),
      );
}

class _VerificationCard extends StatefulWidget {
  const _VerificationCard({required this.latest, required this.onSubmitted});

  final VerificationSubmission? latest;
  final VoidCallback onSubmitted;

  @override
  State<_VerificationCard> createState() => _VerificationCardState();
}

class _VerificationCardState extends State<_VerificationCard> {
  final TextEditingController _reference = TextEditingController();
  String _type = 'aadhaar';
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _reference.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_reference.text.trim().length < 4) {
      setState(() => _error = 'Enter at least the last four characters.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<KarmaRepository>().submitVerification(
            documentType: _type,
            documentRef: _reference.text,
          );
      if (mounted) widget.onSubmitted();
    } on Object catch (error) {
      if (mounted) setState(() => _error = errorMessage(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.latest?.status == 'pending') {
      return KarmaCard(
        color: AppColors.paleGold,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            const Row(
              children: <Widget>[
                Icon(Icons.hourglass_top_rounded, color: AppColors.gold),
                SizedBox(width: 9),
                Text(
                  'Verification under review',
                  style: TextStyle(color: AppColors.gold, fontWeight: FontWeight.w800),
                ),
              ],
            ),
            const SizedBox(height: 7),
            Text(
              'Submitted ${compactDate(widget.latest!.createdAt)}. Approval raises your Karma and unlocks worker onboarding.',
              style: const TextStyle(color: AppColors.textMuted, height: 1.4),
            ),
          ],
        ),
      );
    }

    return KarmaCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          const SectionLabel('Want to take work?'),
          const SizedBox(height: 10),
          const Text(
            'Verify your identity first. Only the last four characters are stored — never the full document number.',
            style: TextStyle(color: AppColors.textMuted),
          ),
          if (widget.latest?.status == 'rejected') ...<Widget>[
            const SizedBox(height: 9),
            const Text(
              'Your previous submission was not approved. You can submit another document.',
              style: TextStyle(color: AppColors.rose, fontSize: 12.5),
            ),
          ],
          const SizedBox(height: 14),
          DropdownButtonFormField<String>(
            initialValue: _type,
            decoration: const InputDecoration(labelText: 'Document'),
            items: const <DropdownMenuItem<String>>[
              DropdownMenuItem(value: 'aadhaar', child: Text('Aadhaar · Gold tier')),
              DropdownMenuItem(value: 'pan', child: Text('PAN · Silver tier')),
              DropdownMenuItem(value: 'govt_id', child: Text('Government ID · Bronze tier')),
            ],
            onChanged: (String? value) => setState(() => _type = value ?? _type),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _reference,
            obscureText: true,
            decoration: const InputDecoration(
              labelText: 'Document number',
              prefixIcon: Icon(Icons.badge_outlined),
            ),
          ),
          if (_error != null) ...<Widget>[
            const SizedBox(height: 8),
            Text(_error!, style: const TextStyle(color: AppColors.rose)),
          ],
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: _busy ? null : _submit,
            icon: const Icon(Icons.shield_outlined),
            label: Text(_busy ? 'Submitting…' : 'Submit securely'),
          ),
        ],
      ),
    );
  }
}

class _WorkerOnboardingCard extends StatefulWidget {
  const _WorkerOnboardingCard({required this.categories, required this.onDone});

  final List<ServiceCategory> categories;
  final VoidCallback onDone;

  @override
  State<_WorkerOnboardingCard> createState() => _WorkerOnboardingCardState();
}

class _WorkerOnboardingCardState extends State<_WorkerOnboardingCard> {
  final TextEditingController _rate = TextEditingController(text: '350');
  final TextEditingController _bio = TextEditingController();
  final TextEditingController _skills = TextEditingController();
  int? _categoryId;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _rate.dispose();
    _bio.dispose();
    _skills.dispose();
    super.dispose();
  }

  Future<void> _register() async {
    final double? rate = double.tryParse(_rate.text.trim());
    if (_categoryId == null || rate == null || rate <= 0) {
      setState(() => _error = 'Choose a category and enter a valid hourly rate.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<KarmaRepository>().registerWorker(
            categoryId: _categoryId!,
            hourlyRate: rate,
            bio: _bio.text,
            skills: _skills.text
                .split(',')
                .map((String item) => item.trim())
                .where((String item) => item.isNotEmpty)
                .toList(),
          );
      HapticFeedback.mediumImpact();
      if (mounted) widget.onDone();
    } on Object catch (error) {
      if (mounted) setState(() => _error = errorMessage(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => KarmaCard(
        color: AppColors.paleLime,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            const SectionLabel('Identity approved'),
            const SizedBox(height: 8),
            Text('Build your work profile', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 5),
            const Text(
              'Tell nearby customers what you do. You can go online after this step.',
              style: TextStyle(color: AppColors.textMuted),
            ),
            const SizedBox(height: 13),
            DropdownButtonFormField<int>(
              initialValue: _categoryId,
              decoration: const InputDecoration(labelText: 'Primary service'),
              items: widget.categories
                  .map(
                    (ServiceCategory category) => DropdownMenuItem<int>(
                      value: category.id,
                      child: Text('${category.emoji}  ${category.name}'),
                    ),
                  )
                  .toList(growable: false),
              onChanged: (int? value) => setState(() => _categoryId = value),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _rate,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                labelText: 'Hourly rate',
                prefixText: '₹ ',
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _skills,
              decoration: const InputDecoration(
                labelText: 'Skills · comma separated',
                hintText: 'rewiring, fault finding, installation',
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _bio,
              minLines: 2,
              maxLines: 5,
              maxLength: 2000,
              decoration: const InputDecoration(
                labelText: 'Work bio',
                alignLabelWithHint: true,
              ),
            ),
            if (_error != null) Text(_error!, style: const TextStyle(color: AppColors.rose)),
            const SizedBox(height: 10),
            FilledButton(
              onPressed: _busy ? null : _register,
              child: Text(_busy ? 'Creating profile…' : 'Open work profile'),
            ),
          ],
        ),
      );
}

class _SafetyCard extends StatelessWidget {
  const _SafetyCard({required this.contacts, required this.onAdd, required this.onRemove});

  final List<TrustedContact>? contacts;
  final VoidCallback onAdd;
  final ValueChanged<TrustedContact> onRemove;

  @override
  Widget build(BuildContext context) => KarmaCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            SectionLabel(
              'Safety circle',
              trailing: Text(
                '${contacts?.length ?? 0}/3',
                style: const TextStyle(color: AppColors.textFaint, fontSize: 12),
              ),
            ),
            const SizedBox(height: 9),
            const Text(
              'Trusted contacts receive your SOS details during an active gig.',
              style: TextStyle(color: AppColors.textMuted),
            ),
            const SizedBox(height: 10),
            if (contacts == null)
              const Center(child: CircularProgressIndicator())
            else if (contacts!.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 10),
                child: Text(
                  'No contacts yet. Add someone you trust before your next gig.',
                  style: TextStyle(color: AppColors.textFaint, fontSize: 12.5),
                ),
              )
            else
              ...contacts!.map(
                (TrustedContact contact) => ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: UserAvatar(name: contact.name, radius: 18),
                  title: Text(contact.name, style: const TextStyle(fontWeight: FontWeight.w700)),
                  subtitle: Text(
                    '${contact.relationship.isEmpty ? 'Trusted contact' : contact.relationship} · ${contact.phone}',
                  ),
                  trailing: IconButton(
                    tooltip: 'Remove ${contact.name}',
                    onPressed: () => onRemove(contact),
                    icon: const Icon(Icons.remove_circle_outline, color: AppColors.rose),
                  ),
                ),
              ),
            OutlinedButton.icon(
              onPressed: (contacts?.length ?? 3) < 3 ? onAdd : null,
              icon: const Icon(Icons.person_add_alt_1_outlined),
              label: const Text('Add trusted contact'),
            ),
          ],
        ),
      );
}

class _ContactDialog extends StatefulWidget {
  const _ContactDialog();

  @override
  State<_ContactDialog> createState() => _ContactDialogState();
}

class _ContactDialogState extends State<_ContactDialog> {
  final TextEditingController _name = TextEditingController();
  final TextEditingController _phone = TextEditingController();
  final TextEditingController _relationship = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    _relationship.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_name.text.trim().isEmpty || _phone.text.trim().length < 8) {
      setState(() => _error = 'Enter a name and valid phone number.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final TrustedContact contact =
          await context.read<KarmaRepository>().addTrustedContact(
                name: _name.text,
                phone: _phone.text,
                relationship: _relationship.text,
              );
      if (mounted) Navigator.pop(context, contact);
    } on Object catch (error) {
      if (mounted) setState(() => _error = errorMessage(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Add trusted contact'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              TextField(
                controller: _name,
                autofocus: true,
                textCapitalization: TextCapitalization.words,
                decoration: const InputDecoration(labelText: 'Name'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _phone,
                keyboardType: TextInputType.phone,
                decoration: const InputDecoration(labelText: 'Phone'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _relationship,
                decoration: const InputDecoration(labelText: 'Relationship · optional'),
              ),
              if (_error != null) ...<Widget>[
                const SizedBox(height: 8),
                Text(_error!, style: const TextStyle(color: AppColors.rose)),
              ],
            ],
          ),
        ),
        actions: <Widget>[
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(
            onPressed: _busy ? null : _save,
            child: Text(_busy ? 'Adding…' : 'Add contact'),
          ),
        ],
      );
}
