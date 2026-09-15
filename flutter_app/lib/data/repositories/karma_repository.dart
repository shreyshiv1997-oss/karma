import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../../core/network/api_client.dart';
import '../models/models.dart';

String _mediaReference(String value) {
  final Uri? uri = Uri.tryParse(value);
  if (uri != null && uri.path.startsWith('/api/v1/media/objects/')) {
    return uri.path;
  }
  return value;
}

class FeedPage {
  const FeedPage({required this.posts, required this.fromCache});

  final List<PostModel> posts;
  final bool fromCache;
}

class KarmaRepository {
  KarmaRepository({required ApiClient api, required SharedPreferences preferences})
      : _api = api,
        _preferences = preferences;

  final ApiClient _api;
  final SharedPreferences _preferences;

  ApiClient get api => _api;

  Future<User?> restoreUser() async {
    if (!await _api.restoreSession()) return null;
    try {
      return User.fromJson(jsonMap(await _api.get('/auth/me')));
    } on ApiException catch (error) {
      if (error.statusCode == 401) return null;
      rethrow;
    }
  }

  Future<AuthResult> login({
    required String identifier,
    required String password,
  }) async {
    final String input = identifier.trim();

    Future<AuthResult> attempt(String candidate) async => AuthResult.fromJson(
          jsonMap(
            await _api.post('/auth/login', <String, Object?>{
              'identifier': candidate,
              'password': password,
            }),
          ),
        );

    Future<AuthResult> authenticate() async {
      try {
        // Try the identifier verbatim first: all-numeric handles are valid and
        // must not be unconditionally rewritten as phone numbers.
        return await attempt(input);
      } on ApiException catch (error) {
        final bool looksLikePhone = RegExp(r'^[+\d\s-]{8,}$').hasMatch(input);
        final String normalized = '+${input.replaceAll(RegExp(r'\D'), '')}';
        if (error.statusCode != 401 || !looksLikePhone || normalized == input) {
          rethrow;
        }
        return attempt(normalized);
      }
    }

    final AuthResult result = await authenticate();
    await _saveAuth(result);
    return result;
  }

  Future<AuthResult> register({
    required String handle,
    required String displayName,
    required String identifier,
    required String password,
    required String city,
  }) async {
    final bool email = identifier.contains('@');
    final AuthResult result = AuthResult.fromJson(
      jsonMap(
        await _api.post('/auth/register', <String, Object?>{
          'handle': handle.trim(),
          'display_name': displayName.trim(),
          if (email) 'email': identifier.trim() else 'phone': identifier.trim(),
          'password': password,
          'city': city.trim(),
        }),
      ),
    );
    await _saveAuth(result);
    return result;
  }

  Future<String?> sendOtp(String phone) async {
    final Map<String, Object?> response = jsonMap(
      await _api.post('/auth/otp/send', <String, Object?>{'phone': phone.trim()}),
    );
    return response['dev_otp'] as String?;
  }

  Future<void> verifyOtp({required String phone, required String otp}) async {
    await _api.post('/auth/otp/verify', <String, Object?>{
      'phone': phone.trim(),
      'otp': otp.trim(),
    });
  }

  Future<void> _saveAuth(AuthResult result) => _api.setTokens(
        accessToken: result.accessToken,
        refreshToken: result.refreshToken,
      );

  // Not `clearTokens()`: forgetting the tokens here proves nothing to the server, which would
  // keep accepting them for another 14 days. ApiClient.logout revokes them first, and never
  // throws when the network says otherwise -- a sign-out must not be able to fail.
  Future<void> logout() async => _api.logout();

  Future<User> currentUser() async =>
      User.fromJson(jsonMap(await _api.get('/auth/me')));

  Future<User> grantCapability(String capability) async => User.fromJson(
        jsonMap(await _api.post('/auth/capability/$capability')),
      );

  Future<FeedPage> posts({
    required int userId,
    bool proofOnly = false,
  }) async {
    final String path = '/feed/posts?limit=30${proofOnly ? '&kind=proof' : ''}';
    final String cacheKey = 'feed.$userId.${proofOnly ? 'proof' : 'all'}';
    try {
      final List<PostModel> result = jsonList(await _api.get(path))
          .map((Object? item) => PostModel.fromJson(jsonMap(item)))
          .toList(growable: false);
      await _preferences.setString(
        cacheKey,
        jsonEncode(result.map((PostModel post) => post.toJson()).toList()),
      );
      return FeedPage(posts: result, fromCache: false);
    } on NetworkException {
      final String? cached = _preferences.getString(cacheKey);
      if (cached == null) rethrow;
      final List<PostModel> result = jsonList(jsonDecode(cached))
          .map((Object? item) => PostModel.fromJson(jsonMap(item)))
          .toList(growable: false);
      return FeedPage(posts: result, fromCache: true);
    }
  }

  Future<UploadedMedia> uploadMedia({
    required List<int> bytes,
    required String filename,
    required String purpose,
  }) async =>
      UploadedMedia.fromJson(
        jsonMap(
          await _api.upload(
            '/media/uploads',
            bytes: bytes,
            filename: filename,
            fields: <String, String>{'purpose': purpose},
          ),
        ),
      );

  Future<PostModel> createPost({
    required String body,
    List<String> mediaUrls = const <String>[],
  }) async =>
      PostModel.fromJson(
        jsonMap(
          await _api.post('/feed/posts', <String, Object?>{
            'kind': 'post',
            'body': body.trim(),
            'media_urls': mediaUrls.map(_mediaReference).toList(growable: false),
            'hashtags': <String>[],
          }),
        ),
      );

  Future<PostModel> toggleLike(int postId) async => PostModel.fromJson(
        jsonMap(await _api.post('/feed/posts/$postId/like')),
      );

  Future<List<CommentModel>> comments(int postId) async =>
      jsonList(await _api.get('/feed/posts/$postId/comments'))
          .map((Object? item) => CommentModel.fromJson(jsonMap(item)))
          .toList(growable: false);

  Future<void> addComment(int postId, String body) async {
    await _api.post(
      '/feed/posts/$postId/comment',
      <String, Object?>{'body': body.trim()},
    );
  }

  Future<List<ServiceCategory>> categories() async =>
      jsonList(await _api.get('/categories'))
          .map((Object? item) => ServiceCategory.fromJson(jsonMap(item)))
          .toList(growable: false);

  Future<List<GeocodedPlace>> geocodeAddress(String query) async =>
      jsonList(
        await _api.post('/locations/geocode', <String, Object?>{
          'query': query.trim(),
          'consent': true,
          'limit': 5,
        }),
      )
          .map((Object? item) => GeocodedPlace.fromJson(jsonMap(item)))
          .toList(growable: false);

  Future<GeocodedPlace?> reverseGeocode(double lat, double lng) async {
    final Object? response = await _api.post('/locations/reverse', <String, Object?>{
      'lat': lat,
      'lng': lng,
      'consent': true,
    });
    return response == null ? null : GeocodedPlace.fromJson(jsonMap(response));
  }

  Future<FareBreakdown> estimate({
    required int categoryId,
    required double hours,
    required String urgency,
    required double lat,
    required double lng,
  }) async =>
      FareBreakdown.fromJson(
        jsonMap(
          await _api.post('/gigs/estimate', <String, Object?>{
            'category_id': categoryId,
            'lat': lat,
            'lng': lng,
            'estimated_hours': hours,
            'urgency': urgency,
          }),
        ),
      );

  Future<Gig> createGig({
    required int categoryId,
    required String title,
    required String description,
    required String address,
    required double hours,
    required String urgency,
    required SelectedLocation location,
    List<String> photos = const <String>[],
  }) async =>
      Gig.fromJson(
        jsonMap(
          await _api.post('/gigs', <String, Object?>{
            'category_id': categoryId,
            'title': title.trim(),
            'description': description.trim(),
            'lat': location.lat,
            'lng': location.lng,
            'address_label': address.trim(),
            'location_source': location.source,
            'location_accuracy_m': location.accuracyM,
            'geocoder': location.geocoder,
            'location_consent': location.consent,
            'estimated_hours': hours,
            'urgency': urgency,
            'photos': photos.map(_mediaReference).toList(growable: false),
          }),
        ),
      );

  Future<List<Candidate>> findMatches(int gigId) async =>
      jsonList(
        await _api.post('/matching/find', <String, Object?>{'gig_id': gigId}),
      )
          .map((Object? item) => Candidate.fromJson(jsonMap(item)))
          .toList(growable: false);

  Future<Gig> assign(int gigId, int workerId) async => Gig.fromJson(
        jsonMap(await _api.post('/gigs/$gigId/assign?worker_id=$workerId')),
      );

  Future<GigPayment> secureGigPayment(int gigId) async => GigPayment.fromJson(
        jsonMap(await _api.post('/payments/gigs/$gigId/intent')),
      );

  Future<GigPayment> paymentStatus(int gigId) async => GigPayment.fromJson(
        jsonMap(await _api.get('/payments/gigs/$gigId')),
      );

  Future<GigPayment> syncGigPayment(int gigId) async => GigPayment.fromJson(
        jsonMap(await _api.post('/payments/gigs/$gigId/sync')),
      );

  Future<GigPayment> releaseGigPayment(int gigId) async => GigPayment.fromJson(
        jsonMap(await _api.post('/payments/gigs/$gigId/release')),
      );

  Future<List<Gig>> gigs({required String role}) async =>
      jsonList(await _api.get('/gigs/mine?role=$role'))
          .map((Object? item) => Gig.fromJson(jsonMap(item)))
          .toList(growable: false);

  Future<GigStats> gigStats() async => GigStats.fromJson(
        jsonMap(await _api.get('/gigs/stats/summary')),
      );

  Future<Gig> updateGigStatus(
    int gigId,
    String status, {
    List<String> proofPhotos = const <String>[],
  }) async =>
      Gig.fromJson(
        jsonMap(
          await _api.post('/gigs/$gigId/status', <String, Object?>{
            'status': status,
            'proof_photos': proofPhotos.map(_mediaReference).toList(growable: false),
          }),
        ),
      );

  Future<bool> gigHasReview(int gigId) async =>
      jsonList(await _api.get('/gigs/$gigId/reviews')).isNotEmpty;

  Future<void> reviewGig({
    required int gigId,
    required int rating,
    required String comment,
  }) async {
    await _api.post('/gigs/$gigId/review', <String, Object?>{
      'rating': rating,
      'comment': comment.trim(),
    });
  }

  Future<void> emergency({int? gigId, String note = ''}) async {
    await _api.post('/safety/emergency', <String, Object?>{
      'gig_id': gigId,
      'note': note,
    });
  }

  Future<void> dispute({required int gigId, required String reason}) async {
    await _api.post('/gigs/$gigId/dispute', <String, Object?>{'reason': reason});
  }

  Future<KarmaLedger> karmaLedger() async => KarmaLedger.fromJson(
        jsonMap(await _api.get('/karma/ledger')),
      );

  Future<WorkerProfile> workerProfile({int? publicUserId}) async => WorkerProfile.fromJson(
        jsonMap(
          await _api.get(
            publicUserId == null
                ? '/workers/me/profile'
                : '/workers/$publicUserId',
          ),
        ),
      );

  Future<void> setAvailability({
    required bool available,
    SelectedLocation? location,
  }) async {
    if (available && location == null) {
      throw const FormatException('A fresh device location is required to go online.');
    }
    await _api.patch('/workers/me/location', <String, Object?>{
      if (location != null) ...<String, Object?>{
        'lat': location.lat,
        'lng': location.lng,
        'accuracy_m': location.accuracyM,
        'location_source': 'device',
        'location_consent': location.consent,
      },
      'is_available': available,
    });
  }

  Future<List<VerificationSubmission>> verifications() async =>
      jsonList(await _api.get('/verification/me'))
          .map((Object? item) => VerificationSubmission.fromJson(jsonMap(item)))
          .toList(growable: false);

  Future<VerificationSubmission> submitVerification({
    required String documentType,
    required String documentRef,
  }) async =>
      VerificationSubmission.fromJson(
        jsonMap(
          await _api.post('/verification/submit', <String, Object?>{
            'document_type': documentType,
            'document_ref': documentRef.trim(),
          }),
        ),
      );

  Future<void> registerWorker({
    required int categoryId,
    required double hourlyRate,
    required String bio,
    required List<String> skills,
  }) async {
    await _api.post('/workers/register', <String, Object?>{
      'category_id': categoryId,
      'hourly_rate': hourlyRate,
      'bio': bio.trim(),
      'skills': skills,
    });
  }

  Future<List<TrustedContact>> trustedContacts() async =>
      jsonList(await _api.get('/safety/trusted-contacts'))
          .map((Object? item) => TrustedContact.fromJson(jsonMap(item)))
          .toList(growable: false);

  Future<TrustedContact> addTrustedContact({
    required String name,
    required String phone,
    required String relationship,
  }) async =>
      TrustedContact.fromJson(
        jsonMap(
          await _api.post('/safety/trusted-contacts', <String, Object?>{
            'name': name.trim(),
            'phone': phone.trim(),
            'relationship': relationship.trim(),
          }),
        ),
      );

  Future<void> removeTrustedContact(int id) async {
    await _api.delete('/safety/trusted-contacts/$id');
  }

  Future<AdminAnalytics> adminAnalytics() async => AdminAnalytics.fromJson(
        jsonMap(await _api.get('/admin/analytics')),
      );

  Future<List<AdminVerification>> adminVerifications() async =>
      jsonList(await _api.get('/admin/verifications'))
          .map((Object? item) => AdminVerification.fromJson(jsonMap(item)))
          .toList(growable: false);

  Future<void> reviewVerification({
    required int submissionId,
    required String decision,
    required String note,
  }) async {
    await _api.patch(
      '/admin/verifications/$submissionId',
      <String, Object?>{
        'decision': decision,
        'note': note.trim(),
      },
    );
  }

  Future<List<AdminSafetyIncident>> adminSafetyIncidents() async =>
      jsonList(await _api.get('/admin/safety/incidents'))
          .map((Object? item) => AdminSafetyIncident.fromJson(jsonMap(item)))
          .toList(growable: false);

  Future<void> updateAdminIncident(int incidentId, String status) async {
    await _api.patch(
      '/admin/safety/incidents/$incidentId',
      <String, Object?>{'status': status},
    );
  }

  Future<List<AdminDispute>> adminDisputes() async =>
      jsonList(await _api.get('/admin/disputes'))
          .map((Object? item) => AdminDispute.fromJson(jsonMap(item)))
          .toList(growable: false);

  Future<void> updateAdminDispute(int disputeId, String status) async {
    await _api.patch(
      '/admin/disputes/$disputeId',
      <String, Object?>{'status': status},
    );
  }

  Future<BitchatDevice> registerBitchatDevice(
    Map<String, Object?> payload,
  ) async =>
      BitchatDevice.fromJson(
        jsonMap(await _api.post('/bitchat/devices', payload)),
      );

  Future<BitchatSession> bitchatSession(int gigId) async =>
      BitchatSession.fromJson(
        jsonMap(await _api.get('/bitchat/gigs/$gigId/session')),
      );

  Future<BitchatClaimedPreKey> claimBitchatPreKey({
    required int gigId,
    required String senderDeviceId,
    required String recipientDeviceId,
  }) async =>
      BitchatClaimedPreKey.fromJson(
        jsonMap(
          await _api.post(
            '/bitchat/gigs/$gigId/prekeys/claim',
            <String, Object?>{
              'sender_device_id': senderDeviceId,
              'recipient_device_id': recipientDeviceId,
            },
          ),
        ),
      );

  Future<BitchatEnvelope> sendBitchatEnvelope(
    int gigId,
    BitchatEnvelope envelope,
  ) async =>
      BitchatEnvelope.fromJson(
        jsonMap(
          await _api.post(
            '/bitchat/gigs/$gigId/messages',
            envelope.toApiJson(),
          ),
        ),
      );

  Future<List<BitchatEnvelope>> bitchatInbox({
    required int gigId,
    required String deviceId,
  }) async =>
      jsonList(
        await _api.get(
          '/bitchat/gigs/$gigId/inbox?device_id=${Uri.encodeQueryComponent(deviceId)}',
        ),
      )
          .map((Object? item) => BitchatEnvelope.fromJson(jsonMap(item)))
          .toList(growable: false);

  Future<void> panicAndWipeBitchat({
    required int gigId,
    required String deviceId,
  }) async {
    await _api.post('/bitchat/gigs/$gigId/panic', <String, Object?>{
      'device_id': deviceId,
      'reason': 'panic_and_wipe',
    });
  }

  Future<String> realtimeTicket() async {
    final Map<String, Object?> response =
        jsonMap(await _api.post('/realtime/ticket'));
    return jsonString(response, 'ticket');
  }
}
