import 'dart:async';
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
import '../../data/services/payment_sheet_service.dart';
import '../../shared/widgets/primitives.dart';
import '../auth/session_controller.dart';

class BookingScreen extends StatefulWidget {
  const BookingScreen({super.key, this.preselectedCategory, this.onBooked});

  final String? preselectedCategory;
  final VoidCallback? onBooked;

  @override
  State<BookingScreen> createState() => _BookingScreenState();
}

class _BookingScreenState extends State<BookingScreen> {
  static const List<String> _steps = <String>['What', 'Where', 'Who', 'Payment'];

  final TextEditingController _title = TextEditingController();
  final TextEditingController _description = TextEditingController();
  final TextEditingController _address = TextEditingController();
  final DeviceCapabilitiesService _device = DeviceCapabilitiesService();

  int _step = 0;
  List<ServiceCategory>? _categories;
  ServiceCategory? _category;
  double _hours = 2;
  String _urgency = 'standard';
  FareBreakdown? _fare;
  Gig? _gig;
  GigPayment? _payment;
  List<Candidate>? _matches;
  SelectedLocation? _location;
  String? _reverseAttribution;
  final List<PendingImage> _requestImages = <PendingImage>[];
  List<String>? _uploadedRequestPhotos;
  bool _busy = false;
  Object? _error;
  Timer? _estimateTimer;
  int _estimateRevision = 0;

  @override
  void initState() {
    super.initState();
    _loadCategories();
  }

  @override
  void dispose() {
    _estimateTimer?.cancel();
    _title.dispose();
    _description.dispose();
    _address.dispose();
    super.dispose();
  }

  Future<void> _loadCategories() async {
    if (_error != null) setState(() => _error = null);
    try {
      final List<ServiceCategory> categories =
          await context.read<KarmaRepository>().categories();
      if (!mounted) return;
      ServiceCategory? selected;
      final String wanted = widget.preselectedCategory?.trim().toLowerCase() ?? '';
      for (final ServiceCategory item in categories) {
        if (item.name.toLowerCase() == wanted || item.slug.toLowerCase() == wanted) {
          selected = item;
          break;
        }
      }
      setState(() {
        _categories = categories;
        _category = selected;
      });
      if (selected != null) _scheduleEstimate();
    } on Object catch (error) {
      if (mounted) setState(() => _error = error);
    }
  }

  void _scheduleEstimate() {
    _estimateTimer?.cancel();
    if (_error != null) setState(() => _error = null);
    if (_location == null) {
      if (_fare != null) setState(() => _fare = null);
      return;
    }
    final int revision = ++_estimateRevision;
    _estimateTimer = Timer(
      const Duration(milliseconds: 250),
      () => _estimate(revision),
    );
  }

  Future<void> _estimate(int revision) async {
    final ServiceCategory? category = _category;
    final SelectedLocation? location = _location;
    if (category == null || location == null) return;
    final KarmaRepository repository = context.read<KarmaRepository>();
    try {
      final FareBreakdown fare = await repository.estimate(
            categoryId: category.id,
            hours: _hours,
            urgency: _urgency,
            lat: location.lat,
            lng: location.lng,
          );
      if (mounted &&
          revision == _estimateRevision &&
          category.id == _category?.id) {
        setState(() => _fare = fare);
      }
    } on Object catch (error) {
      if (mounted && revision == _estimateRevision) {
        setState(() => _error = error);
      }
    }
  }

  Future<void> _addRequestImage() async {
    if (_requestImages.length >= 3) return;
    try {
      final PendingImage? image = await _device.pickImage(context);
      if (image != null && mounted) {
        setState(() {
          _requestImages.add(image);
          _uploadedRequestPhotos = null;
        });
      }
    } on Object catch (error) {
      if (mounted) setState(() => _error = error);
    }
  }

  Future<void> _useCurrentLocation() async {
    final bool consented = await confirmLocationConsent(
      context,
      title: 'Use your current location?',
      action: 'Allow once',
      includesGeocoder: true,
    );
    if (!consented || !mounted) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final Position position = await _device.currentPosition();
      if (!mounted) return;
      GeocodedPlace? place;
      try {
        place = await context
            .read<KarmaRepository>()
            .reverseGeocode(position.latitude, position.longitude);
      } on Object {
        // The coordinates remain a real device fix if address lookup is unavailable. The user
        // can type a private service label without that text silently changing the point.
      }
      if (!mounted) return;
      final String label = place?.label ??
          '${position.latitude.toStringAsFixed(5)}, ${position.longitude.toStringAsFixed(5)}';
      setState(() {
        _location = SelectedLocation(
          lat: position.latitude,
          lng: position.longitude,
          label: label,
          source: 'device',
          consent: true,
          accuracyM: position.accuracy,
        );
        _address.text = label;
        _reverseAttribution = place == null
            ? null
            : '${place.provider} · ${place.attribution}';
        _fare = null;
      });
      _scheduleEstimate();
    } on Object catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _searchAddress() async {
    final String query = _address.text.trim();
    if (query.length < 3) {
      setState(() => _error = const FormatException('Type at least 3 characters.'));
      return;
    }
    final bool consented = await confirmAddressLookup(context);
    if (!consented || !mounted) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final List<GeocodedPlace> places =
          await context.read<KarmaRepository>().geocodeAddress(query);
      if (!mounted) return;
      if (places.isEmpty) {
        setState(() => _error = const FormatException('No matching address was found.'));
        return;
      }
      final GeocodedPlace? selected = await showModalBottomSheet<GeocodedPlace>(
        context: context,
        showDragHandle: true,
        useSafeArea: true,
        builder: (BuildContext context) => ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 20),
          children: <Widget>[
            Text('Choose the matching place', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            ...places.map(
              (GeocodedPlace place) => ListTile(
                leading: const Icon(Icons.location_on_outlined),
                title: Text(place.label),
                subtitle: Text('${place.provider} · ${place.attribution}'),
                onTap: () => Navigator.pop(context, place),
              ),
            ),
          ],
        ),
      );
      if (selected == null || !mounted) return;
      setState(() {
        _location = SelectedLocation(
          lat: selected.lat,
          lng: selected.lng,
          label: selected.label,
          source: 'geocoded',
          consent: true,
          geocoder: selected.provider,
        );
        _address.text = selected.label;
        _reverseAttribution = null;
        _fare = null;
      });
      _scheduleEstimate();
    } on Object catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _findWorkers() async {
    final ServiceCategory? category = _category;
    if (category == null) return;
    final SelectedLocation? location = _location;
    if (location == null || _address.text.trim().isEmpty) {
      setState(() => _error = const FormatException(
            'Choose a device location or select an address-search result.',
          ));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final SessionController session = context.read<SessionController>();
      final KarmaRepository repository = context.read<KarmaRepository>();
      if (!(session.user?.can('can_hire') ?? false)) {
        final User updated = await repository.grantCapability('can_hire');
        await session.replaceUser(updated);
      }
      if (!mounted) return;

      final Gig gigForMatching;
      if (_gig case final Gig existing) {
        gigForMatching = existing;
      } else {
        final List<String> photoUrls = List<String>.from(
          _uploadedRequestPhotos ?? const <String>[],
        );
        for (int index = photoUrls.length; index < _requestImages.length; index++) {
          final PendingImage image = _requestImages[index];
          final UploadedMedia media = await repository.uploadMedia(
            bytes: image.bytes,
            filename: image.name,
            purpose: 'gig',
          );
          photoUrls.add(media.url);
          // Preserve each successful upload across a later network failure. Retrying the request
          // should attach those immutable objects, not upload duplicate orphan bytes.
          _uploadedRequestPhotos = List<String>.from(photoUrls);
        }
        final Gig created = await repository.createGig(
          categoryId: category.id,
          title: _title.text,
          description: _description.text,
          address: _address.text,
          hours: _hours,
          urgency: _urgency,
          location: location,
          photos: photoUrls,
        );
        if (!mounted) return;
        // Persist the created gig in local state before matching. If matching
        // fails, retrying must query this gig rather than posting a duplicate.
        setState(() {
          _gig = created;
          _matches = null;
          _step = 2;
        });
        gigForMatching = created;
      }

      final List<Candidate> matches =
          await repository.findMatches(gigForMatching.id);
      if (!mounted) return;
      setState(() {
        _matches = matches;
        _step = 2;
      });
    } on Object catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _changeDetails() async {
    final Gig? gig = _gig;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      // A searching gig has already been persisted. Cancel it before returning
      // to editable details so a second search cannot leave duplicates behind.
      if (gig != null && gig.status == 'searching') {
        await context
            .read<KarmaRepository>()
            .updateGigStatus(gig.id, 'cancelled');
      }
      if (!mounted) return;
      setState(() {
        _gig = null;
        _matches = null;
        _step = 1;
      });
    } on Object catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _book(Candidate candidate) async {
    final Gig? gig = _gig;
    if (gig == null || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final Gig assigned = await context
          .read<KarmaRepository>()
          .assign(gig.id, candidate.userId);
      HapticFeedback.mediumImpact();
      if (!mounted) return;
      setState(() {
        _gig = assigned;
        _step = 3;
      });
      widget.onBooked?.call();

      // Assignment is already durable. If PaymentSheet is cancelled or the network drops,
      // keep the booked gig visible and offer an explicit retry instead of assigning twice.
      try {
        final GigPayment payment = await PaymentSheetService(
          context.read<KarmaRepository>(),
        ).secure(assigned.id);
        if (mounted) setState(() => _payment = payment);
      } on Object catch (error) {
        if (mounted && !isPaymentSheetCancellation(error)) {
          setState(() => _error = error);
        }
      }
    } on Object catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _secureBookedGig() async {
    final Gig? gig = _gig;
    if (gig == null || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final GigPayment payment = await PaymentSheetService(
        context.read<KarmaRepository>(),
      ).secure(gig.id);
      if (!mounted) return;
      setState(() => _payment = payment);
      HapticFeedback.mediumImpact();
    } on Object catch (error) {
      if (mounted && !isPaymentSheetCancellation(error)) {
        setState(() => _error = error);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('Post a gig'),
          leading: IconButton(
            tooltip: _step > 0 && _step < 2 ? 'Previous step' : 'Close',
            onPressed: () {
              if (_step == 1) {
                setState(() => _step = 0);
              } else {
                Navigator.pop(context);
              }
            },
            icon: Icon(_step == 1 ? Icons.arrow_back_rounded : Icons.close_rounded),
          ),
        ),
        body: Column(
          children: <Widget>[
            _StepHeader(step: _step, steps: _steps),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 40),
                child: Align(
                  alignment: Alignment.topCenter,
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: AppTheme.contentMaxWidth),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: <Widget>[
                        if (_error != null) ...<Widget>[
                          _InlineError(message: errorMessage(_error!)),
                          const SizedBox(height: 12),
                        ],
                        AnimatedSwitcher(
                          duration: AppTheme.enter,
                          switchInCurve: Curves.easeOutCubic,
                          child: switch (_step) {
                            0 => _buildWhat(),
                            1 => _buildWhere(),
                            2 => _buildMatches(),
                            _ => _buildSuccess(),
                          },
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      );

  Widget _buildWhat() => KarmaCard(
        key: const ValueKey<int>(0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Text('What do you need done?', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 4),
            const Text(
              'Choose the closest service. You can add the specifics next.',
              style: TextStyle(color: AppColors.textMuted),
            ),
            const SizedBox(height: 16),
            if (_categories == null)
              SizedBox(
                height: 110,
                child: Center(
                  child: _error == null
                      ? const CircularProgressIndicator()
                      : TextButton.icon(
                          onPressed: _loadCategories,
                          icon: const Icon(Icons.refresh_rounded),
                          label: const Text('Retry services'),
                        ),
                ),
              )
            else
              LayoutBuilder(
                builder: (BuildContext context, BoxConstraints constraints) {
                  final int columns = constraints.maxWidth > 560 ? 4 : 3;
                  return GridView.builder(
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    itemCount: _categories!.length,
                    gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: columns,
                      crossAxisSpacing: 8,
                      mainAxisSpacing: 8,
                      childAspectRatio: 1.08,
                    ),
                    itemBuilder: (BuildContext context, int index) {
                      final ServiceCategory category = _categories![index];
                      final bool selected = _category?.id == category.id;
                      return Semantics(
                        selected: selected,
                        button: true,
                        child: InkWell(
                          borderRadius: BorderRadius.circular(12),
                          onTap: () {
                            setState(() {
                              _category = category;
                              _fare = null;
                            });
                            _scheduleEstimate();
                          },
                          child: AnimatedContainer(
                            duration: AppTheme.quick,
                            padding: const EdgeInsets.all(8),
                            decoration: BoxDecoration(
                              color: selected ? AppColors.paleViolet : AppColors.surface,
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(
                                color: selected ? AppColors.violet : AppColors.lineStrong,
                                width: selected ? 1.5 : 1,
                              ),
                            ),
                            child: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: <Widget>[
                                Text(category.emoji, style: const TextStyle(fontSize: 25)),
                                const SizedBox(height: 5),
                                Text(
                                  category.name,
                                  maxLines: 2,
                                  textAlign: TextAlign.center,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    fontSize: 12.5,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      );
                    },
                  );
                },
              ),
            const SizedBox(height: 16),
            TextField(
              controller: _title,
              maxLength: 140,
              textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(
                labelText: 'Short title',
                hintText: 'Rewire 3-room flat',
                counterText: '',
              ),
              onChanged: (_) => setState(() {}),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _description,
              minLines: 3,
              maxLines: 6,
              maxLength: 2000,
              textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(
                labelText: 'Details',
                hintText: 'What should a professional know before accepting?',
                alignLabelWithHint: true,
              ),
            ),
            const SizedBox(height: 12),
            if (_requestImages.isNotEmpty) ...<Widget>[
              SizedBox(
                height: 74,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: _requestImages.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (BuildContext context, int index) => Stack(
                    children: <Widget>[
                      ClipRRect(
                        borderRadius: BorderRadius.circular(10),
                        child: SizedBox.square(
                          dimension: 72,
                          child: Image.memory(_requestImages[index].bytes, fit: BoxFit.cover),
                        ),
                      ),
                      Positioned(
                        right: 2,
                        top: 2,
                        child: IconButton.filledTonal(
                          visualDensity: VisualDensity.compact,
                          tooltip: 'Remove photo',
                          onPressed: () => setState(() {
                            _requestImages.removeAt(index);
                            _uploadedRequestPhotos = null;
                          }),
                          icon: const Icon(Icons.close_rounded, size: 16),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 8),
            ],
            OutlinedButton.icon(
              onPressed: _requestImages.length >= 3 ? null : _addRequestImage,
              icon: const Icon(Icons.add_a_photo_outlined),
              label: Text(
                _requestImages.isEmpty
                    ? 'Add request photos · optional'
                    : 'Add another photo · ${_requestImages.length}/3',
              ),
            ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _category != null && _title.text.trim().length >= 3
                  ? () => setState(() => _step = 1)
                  : null,
              child: const Text('Continue'),
            ),
          ],
        ),
      );

  Widget _buildWhere() => KarmaCard(
        key: const ValueKey<int>(1),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Text('When and where?', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 16),
            TextField(
              controller: _address,
              maxLength: 200,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(
                labelText: 'Service address or landmark',
                prefixIcon: Icon(Icons.location_on_outlined),
                counterText: '',
              ),
            ),
            const SizedBox(height: 10),
            Row(
              children: <Widget>[
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: _busy ? null : _searchAddress,
                    icon: const Icon(Icons.manage_search_rounded),
                    label: const Text('Search address'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: FilledButton.tonalIcon(
                    onPressed: _busy ? null : _useCurrentLocation,
                    icon: const Icon(Icons.my_location_rounded),
                    label: const Text('Use current'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              _location == null
                  ? 'No coordinates selected. Typing an address does not silently place a pin; search it or consent to a one-time device fix.'
                  : _location!.source == 'device'
                      ? 'Using a one-time device fix${_location!.accuracyM == null ? '' : ' · ±${_location!.accuracyM!.round()} m'}${_reverseAttribution == null ? '' : ' · label by $_reverseAttribution'}. Editing the label does not move the coordinates.'
                      : 'Using the result you selected from ${_location!.geocoder}. Editing the label does not move the selected coordinates.',
              style: TextStyle(
                color: _location == null ? AppColors.gold : AppColors.textFaint,
                fontSize: 11.5,
                height: 1.4,
              ),
            ),
            const SizedBox(height: 18),
            Row(
              children: <Widget>[
                const Expanded(
                  child: Text(
                    'Estimated time',
                    style: TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
                Text(
                  '${_hours.toStringAsFixed(_hours % 1 == 0 ? 0 : 1)} hours',
                  style: const TextStyle(
                    color: AppColors.violetInk,
                    fontWeight: FontWeight.w700,
                    fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
                  ),
                ),
              ],
            ),
            Slider(
              value: _hours,
              min: 1,
              max: 12,
              divisions: 22,
              label: '$_hours hours',
              onChanged: (double value) {
                setState(() {
                  _hours = value;
                  _fare = null;
                });
                _scheduleEstimate();
              },
            ),
            const SizedBox(height: 6),
            const Text('Urgency', style: TextStyle(fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            SegmentedButton<String>(
              showSelectedIcon: false,
              segments: const <ButtonSegment<String>>[
                ButtonSegment<String>(
                  value: 'standard',
                  icon: Icon(Icons.schedule_rounded),
                  label: Text('Standard'),
                ),
                ButtonSegment<String>(
                  value: 'urgent',
                  icon: Icon(Icons.bolt_rounded),
                  label: Text('Urgent · today'),
                ),
              ],
              selected: <String>{_urgency},
              onSelectionChanged: (Set<String> value) {
                setState(() {
                  _urgency = value.first;
                  _fare = null;
                });
                _scheduleEstimate();
              },
            ),
            const SizedBox(height: 18),
            AnimatedSwitcher(
              duration: AppTheme.quick,
              child: _location == null
                  ? const Padding(
                      padding: EdgeInsets.symmetric(vertical: 20),
                      child: Text(
                        'Choose a location to calculate the transparent estimate.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: AppColors.textMuted),
                      ),
                    )
                  : _fare == null
                      ? SizedBox(
                          height: 110,
                          child: Center(
                            child: _error == null
                                ? const CircularProgressIndicator()
                                : TextButton.icon(
                                    onPressed: _scheduleEstimate,
                                    icon: const Icon(Icons.refresh_rounded),
                                    label: const Text('Retry estimate'),
                                  ),
                          ),
                        )
                      : FareBreakdownView(fare: _fare!),
            ),
            const SizedBox(height: 18),
            Row(
              children: <Widget>[
                OutlinedButton(
                  onPressed: () => setState(() => _step = 0),
                  child: const Text('Back'),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton.icon(
                    onPressed: _busy || _location == null ? null : _findWorkers,
                    icon: _busy
                        ? const SizedBox.square(
                            dimension: 18,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.search_rounded),
                    label: Text(_busy ? 'Finding workers…' : 'Find workers'),
                  ),
                ),
              ],
            ),
          ],
        ),
      );

  Widget _buildMatches() {
    final List<Candidate> matches = _matches ?? <Candidate>[];
    return Column(
      key: const ValueKey<int>(2),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Text(
          '${matches.length} verified worker${matches.length == 1 ? '' : 's'} nearby',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 4),
        const Text(
          'Ranked by work karma, distance, rating and availability — never social popularity.',
          style: TextStyle(color: AppColors.textMuted),
        ),
        const SizedBox(height: 14),
        if (_matches == null)
          Column(
            children: <Widget>[
              const LoadingCards(count: 2),
              if (!_busy)
                FilledButton.icon(
                  onPressed: _findWorkers,
                  icon: const Icon(Icons.refresh_rounded),
                  label: const Text('Try matching again'),
                ),
            ],
          )
        else if (matches.isEmpty)
          EmptyState(
            icon: Icons.location_searching_rounded,
            title: 'Nobody nearby right now',
            message: 'Try again, or change the request details.',
            action: FilledButton.icon(
              onPressed: _busy ? null : _findWorkers,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Try matching again'),
            ),
          )
        else
          ...matches.indexed.map(((int, Candidate) record) {
            return Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: _CandidateCard(
                candidate: record.$2,
                rank: record.$1 + 1,
                busy: _busy,
                onBook: () => _book(record.$2),
              ),
            );
          }),
        OutlinedButton.icon(
          onPressed: _busy ? null : _changeDetails,
          icon: const Icon(Icons.arrow_back_rounded),
          label: const Text('Change details'),
        ),
      ],
    );
  }

  Widget _buildSuccess() {
    final Gig gig = _gig!;
    final bool secured = _payment?.isSecured ?? false;
    return KarmaCard(
      key: const ValueKey<int>(3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Align(
            child: Container(
              width: 68,
              height: 68,
              decoration: BoxDecoration(
                color: secured ? AppColors.paleLime : AppColors.paleGold,
                shape: BoxShape.circle,
              ),
              child: Icon(
                secured ? Icons.lock_rounded : Icons.credit_card_rounded,
                color: secured ? AppColors.lime : AppColors.gold,
                size: 36,
              ),
            ),
          ),
          const SizedBox(height: 14),
          Text(
            secured ? 'Payment secured' : 'Secure your booking',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 5),
          Text(
            '${gig.title} · gig #${gig.id}',
            textAlign: TextAlign.center,
            style: const TextStyle(color: AppColors.textMuted),
          ),
          const SizedBox(height: 20),
          FareBreakdownView(fare: gig.fareBreakdown, emphasizeTotal: true),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: secured ? AppColors.paleLime : AppColors.paleGold,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              children: <Widget>[
                Icon(
                  secured ? Icons.verified_user_rounded : Icons.info_outline_rounded,
                  color: secured ? AppColors.lime : AppColors.gold,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    secured
                        ? 'Stripe authorized ${inr(gig.total)}. It is captured only after you approve the completed work.'
                        : 'The worker cannot begin travelling until the fixed price is authorized with Stripe.',
                    style: const TextStyle(fontSize: 12.5, color: AppColors.textMuted),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          if (!secured) ...<Widget>[
            FilledButton.icon(
              onPressed: _busy ? null : _secureBookedGig,
              icon: const Icon(Icons.lock_rounded),
              label: Text(_busy ? 'Opening Stripe…' : 'Secure ${inr(gig.total)}'),
            ),
            const SizedBox(height: 8),
          ],
          OutlinedButton.icon(
            onPressed: () => Navigator.pop(context, true),
            icon: const Icon(Icons.route_outlined),
            label: Text(secured ? 'Track this gig' : 'Secure later from Your work'),
          ),
        ],
      ),
    );
  }
}

class _StepHeader extends StatelessWidget {
  const _StepHeader({required this.step, required this.steps});

  final int step;
  final List<String> steps;

  @override
  Widget build(BuildContext context) => Semantics(
        label: 'Step ${step + 1} of ${steps.length}: ${steps[step]}',
        child: Container(
          color: AppColors.paper,
          padding: const EdgeInsets.fromLTRB(16, 2, 16, 10),
          child: Align(
            alignment: Alignment.center,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: AppTheme.contentMaxWidth),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  ClipRRect(
                    borderRadius: BorderRadius.circular(999),
                    child: LinearProgressIndicator(
                      value: (step + 1) / steps.length,
                      minHeight: 5,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Step ${step + 1} of ${steps.length} · ${steps[step]}',
                    style: const TextStyle(color: AppColors.textFaint, fontSize: 12),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
}

class FareBreakdownView extends StatelessWidget {
  const FareBreakdownView({
    required this.fare,
    super.key,
    this.emphasizeTotal = false,
  });

  final FareBreakdown fare;
  final bool emphasizeTotal;

  @override
  Widget build(BuildContext context) {
    final List<(String, num)> rows = <(String, num)>[
      ('Base service', fare.baseFare),
      ('Time', fare.timeFare),
      if (fare.distanceFare > 0) ('Travel', fare.distanceFare),
      ('Platform fee', fare.platformFee),
    ];
    final List<String> multipliers = <String>[
      if (fare.skillMultiplier != 1) 'Skill ×${fare.skillMultiplier}',
      if (fare.urgencyMultiplier != 1) 'Urgency ×${fare.urgencyMultiplier}',
      if (fare.nightMultiplier != 1) 'Night ×${fare.nightMultiplier}',
    ];
    return Container(
      padding: const EdgeInsets.all(15),
      decoration: BoxDecoration(
        color: AppColors.surfaceMuted,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        children: <Widget>[
          const SectionLabel('Transparent estimate'),
          const SizedBox(height: 10),
          ...rows.map(
            ((String, num) row) => Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                children: <Widget>[
                  Expanded(
                    child: Text(row.$1, style: const TextStyle(color: AppColors.textMuted)),
                  ),
                  Text(
                    inr(row.$2),
                    style: const TextStyle(
                      fontWeight: FontWeight.w600,
                      fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (multipliers.isNotEmpty) ...<Widget>[
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: Wrap(
                spacing: 6,
                runSpacing: 6,
                children: multipliers
                    .map(
                      (String text) => Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(
                          color: AppColors.paleGold,
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: Text(
                          text,
                          style: const TextStyle(
                            color: AppColors.gold,
                            fontSize: 11.5,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    )
                    .toList(growable: false),
              ),
            ),
          ],
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 9),
            child: Divider(),
          ),
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  'Estimated total',
                  style: TextStyle(
                    fontSize: emphasizeTotal ? 16 : 14,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              Text(
                inr(fare.total),
                style: TextStyle(
                  fontSize: emphasizeTotal ? 24 : 20,
                  fontWeight: FontWeight.w800,
                  color: AppColors.ink,
                  fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _CandidateCard extends StatelessWidget {
  const _CandidateCard({
    required this.candidate,
    required this.rank,
    required this.busy,
    required this.onBook,
  });

  final Candidate candidate;
  final int rank;
  final bool busy;
  final VoidCallback onBook;

  @override
  Widget build(BuildContext context) => KarmaCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Row(
              children: <Widget>[
                Stack(
                  clipBehavior: Clip.none,
                  children: <Widget>[
                    UserAvatar(
                      name: candidate.displayName,
                      url: candidate.avatarUrl,
                      radius: 25,
                    ),
                    Positioned(
                      left: -5,
                      top: -5,
                      child: Container(
                        width: 21,
                        height: 21,
                        alignment: Alignment.center,
                        decoration: const BoxDecoration(
                          color: AppColors.ink,
                          shape: BoxShape.circle,
                        ),
                        child: Text(
                          '$rank',
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 10,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Row(
                        children: <Widget>[
                          Flexible(
                            child: Text(
                              candidate.displayName,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                          ),
                          const SizedBox(width: 6),
                          TierBadge(tier: candidate.verificationTier),
                        ],
                      ),
                      Text(
                        '@${candidate.handle} · ${candidate.distanceKm.toStringAsFixed(1)} km · ${candidate.etaMinutes} min',
                        style: const TextStyle(color: AppColors.textFaint, fontSize: 12.5),
                      ),
                    ],
                  ),
                ),
                KarmaRing(value: candidate.karma, size: 46),
              ],
            ),
            const SizedBox(height: 13),
            Wrap(
              spacing: 12,
              runSpacing: 6,
              children: <Widget>[
                _Metric(icon: Icons.star_rounded, value: candidate.rating.toStringAsFixed(1)),
                _Metric(icon: Icons.work_outline, value: '${candidate.totalJobs} jobs'),
                _Metric(icon: Icons.verified_outlined, value: '${candidate.proofCount} proofs'),
                _Metric(icon: Icons.payments_outlined, value: '${inr(candidate.hourlyRate)}/hr'),
              ],
            ),
            if (candidate.reasons.isNotEmpty) ...<Widget>[
              const SizedBox(height: 13),
              Container(
                padding: const EdgeInsets.all(11),
                decoration: BoxDecoration(
                  color: AppColors.paleCyan,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    const Text(
                      'WHY THIS MATCH',
                      style: TextStyle(
                        color: AppColors.cyan,
                        fontSize: 10.5,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 0.7,
                      ),
                    ),
                    const SizedBox(height: 5),
                    ...candidate.reasons.take(3).map(
                          (String reason) => Padding(
                            padding: const EdgeInsets.only(top: 3),
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: <Widget>[
                                const Text('✓  ', style: TextStyle(color: AppColors.cyan)),
                                Expanded(
                                  child: Text(
                                    reason,
                                    style: const TextStyle(fontSize: 12.5, height: 1.35),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 13),
            FilledButton(
              onPressed: busy ? null : onBook,
              child: Text(busy ? 'Booking…' : 'Book ${candidate.displayName.split(' ').first}'),
            ),
          ],
        ),
      );
}

class _Metric extends StatelessWidget {
  const _Metric({required this.icon, required this.value});

  final IconData icon;
  final String value;

  @override
  Widget build(BuildContext context) => Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Icon(icon, size: 16, color: AppColors.gold),
          const SizedBox(width: 4),
          Text(value, style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)),
        ],
      );
}

class _InlineError extends StatelessWidget {
  const _InlineError({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) => Semantics(
        liveRegion: true,
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0xFFFFF5F7),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: AppColors.rose.withValues(alpha: 0.3)),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const Icon(Icons.error_outline, color: AppColors.rose, size: 20),
              const SizedBox(width: 9),
              Expanded(
                child: Text(
                  message,
                  style: const TextStyle(color: AppColors.rose, fontWeight: FontWeight.w600),
                ),
              ),
            ],
          ),
        ),
      );
}
