import 'package:flutter_test/flutter_test.dart';
import 'package:karma_app/data/models/models.dart';

void main() {
  group('API models', () {
    test('parses and round-trips cached proof posts', () {
      final Map<String, Object?> json = <String, Object?>{
        'id': 7,
        'author_id': 2,
        'kind': 'proof',
        'body': 'Rewired a family home',
        'media_urls': <String>['https://example.com/before.jpg'],
        'hashtags': <String>['electrician'],
        'gig_id': 42,
        'before_url': 'https://example.com/before.jpg',
        'after_url': 'https://example.com/after.jpg',
        'category_name': 'Electrical',
        'amount_earned': 1275.5,
        'rating': 5,
        'likes_count': 12,
        'comments_count': 3,
        'created_at': '2026-09-13T10:00:00Z',
        'author_name': 'Ramesh Kumar',
        'author_handle': 'ramesh.electric',
        'author_karma': 88,
        'author_tier': 'gold',
      };

      final PostModel post = PostModel.fromJson(json);
      final PostModel cached = PostModel.fromJson(post.toJson());

      expect(post.isProof, isTrue);
      expect(cached.gigId, 42);
      expect(cached.amountEarned, 1275.5);
      expect(cached.authorKarma, 88);
      expect(cached.beforeUrl, contains('before'));
    });

    test('parses admin queues and preserves case identity on status changes', () {
      final AdminAnalytics analytics = AdminAnalytics.fromJson(
        <String, Object?>{
          'users': 42,
          'workers': 11,
          'gigs': 18,
          'gigs_completed': 15,
          'posts': 70,
          'proof_posts': 12,
          'proof_posts_from_gigs': 12,
          'pending_verifications': 3,
          'open_incidents': 2,
          'open_disputes': 1,
          'proof_rate': 0.8,
        },
      );
      final AdminSafetyIncident incident = AdminSafetyIncident.fromJson(
        <String, Object?>{
          'id': 9,
          'raised_by': 4,
          'raised_by_name': 'Priya',
          'raised_by_handle': 'priya',
          'against_user_id': 6,
          'gig_id': 22,
          'lat': 22.0869,
          'lng': 79.5435,
          'note': 'Emergency signal',
          'status': 'open',
          'created_at': '2026-09-13T10:00:00Z',
        },
      );

      expect(analytics.pendingVerifications, 3);
      expect(analytics.proofRate, 0.8);
      expect(incident.copyWith(status: 'resolved').id, 9);
      expect(incident.copyWith(status: 'resolved').status, 'resolved');
    });

    test('parses Stripe authorization without exposing card data', () {
      final GigPayment payment = GigPayment.fromJson(<String, Object?>{
        'gig_id': 42,
        'provider': 'stripe',
        'status': 'authorized',
        'amount': 1500,
        'platform_fee': 225,
        'worker_payout': 1275,
        'currency': 'INR',
        'payment_intent_id': 'pi_test_42',
        'client_secret': 'pi_test_42_secret_client_only',
        'publishable_key': 'pk_test_example',
        'authorized_at': '2026-09-13T10:00:00Z',
        'captured_at': null,
        'released_at': null,
        'refunded_at': null,
        'failure_message': null,
      });

      expect(payment.isSecured, isTrue);
      expect(payment.workerPayout, 1275);
      expect(payment.authorizedAt, isNotNull);
      expect(payment.releasedAt, isNull);
    });

    test('keeps work and social karma separate', () {
      final KarmaLedger ledger = KarmaLedger.fromJson(<String, Object?>{
        'blended': 73,
        'work': 81,
        'social': 61,
        'band': 'trusted',
        'events': <Object?>[
          <String, Object?>{
            'id': 1,
            'event_type': 'GIG_COMPLETED',
            'domain': 'work',
            'delta': 5,
            'reason': 'Completed work',
            'created_at': '2026-09-13T10:00:00Z',
          },
        ],
        'total_events': 1,
        'truncated': false,
      });

      expect(ledger.work, 81);
      expect(ledger.social, 61);
      expect(ledger.events.single.domain, 'work');
    });

    test('parses immutable media and attributed geocoding results', () {
      final UploadedMedia media = UploadedMedia.fromJson(<String, Object?>{
        'id': '4a78514c-b765-4c0f-8f4f-36ab5eaacb14',
        'purpose': 'proof_before',
        'url': 'https://karma.test/api/v1/media/objects/4a78514c-b765-4c0f-8f4f-36ab5eaacb14',
        'content_type': 'image/png',
        'byte_size': 1024,
        'sha256': 'abc123',
      });
      final GeocodedPlace place = GeocodedPlace.fromJson(<String, Object?>{
        'place_id': 'node:42',
        'label': 'Vijay Nagar, Indore',
        'lat': 22.7533,
        'lng': 75.8937,
        'provider': 'OpenStreetMap Nominatim',
        'attribution': '© OpenStreetMap contributors',
      });

      expect(media.purpose, 'proof_before');
      expect(media.byteSize, 1024);
      expect(place.provider, 'OpenStreetMap Nominatim');
      expect(place.lat, closeTo(22.7533, 0.00001));
    });
  });
}
