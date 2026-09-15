import '../../core/network/api_client.dart';

DateTime _date(Map<String, Object?> map, String key) =>
    DateTime.tryParse(jsonString(map, key)) ?? DateTime.fromMillisecondsSinceEpoch(0);

class User {
  const User({
    required this.id,
    required this.uuid,
    required this.handle,
    required this.displayName,
    required this.bio,
    required this.capabilities,
    required this.isVerified,
    required this.verificationTier,
    required this.karma,
    required this.karmaWork,
    required this.karmaSocial,
    required this.streak,
    required this.followersCount,
    required this.followingCount,
    required this.postsCount,
    this.email,
    this.phone,
    this.avatarUrl,
    this.city,
    this.statusText,
  });

  factory User.fromJson(Map<String, Object?> map) => User(
        id: jsonInt(map, 'id'),
        uuid: jsonString(map, 'uuid'),
        handle: jsonString(map, 'handle'),
        displayName: jsonString(map, 'display_name'),
        email: map['email'] as String?,
        phone: map['phone'] as String?,
        avatarUrl: map['avatar_url'] as String?,
        bio: jsonString(map, 'bio'),
        city: map['city'] as String?,
        capabilities: jsonStrings(map, 'capabilities'),
        isVerified: jsonBool(map, 'is_verified'),
        verificationTier: jsonString(map, 'verification_tier', fallback: 'none'),
        karma: jsonInt(map, 'karma', fallback: 50),
        karmaWork: jsonInt(map, 'karma_work', fallback: 50),
        karmaSocial: jsonInt(map, 'karma_social', fallback: 50),
        streak: jsonInt(map, 'streak'),
        followersCount: jsonInt(map, 'followers_count'),
        followingCount: jsonInt(map, 'following_count'),
        postsCount: jsonInt(map, 'posts_count'),
        statusText: map['status_text'] as String?,
      );

  final int id;
  final String uuid;
  final String handle;
  final String displayName;
  final String? email;
  final String? phone;
  final String? avatarUrl;
  final String bio;
  final String? city;
  final List<String> capabilities;
  final bool isVerified;
  final String verificationTier;
  final int karma;
  final int karmaWork;
  final int karmaSocial;
  final int streak;
  final int followersCount;
  final int followingCount;
  final int postsCount;
  final String? statusText;

  bool can(String capability) => capabilities.contains(capability);
}

class AuthResult {
  const AuthResult({
    required this.user,
    required this.accessToken,
    required this.refreshToken,
  });

  factory AuthResult.fromJson(Map<String, Object?> map) => AuthResult(
        user: User.fromJson(jsonMap(map['user'])),
        accessToken: jsonString(map, 'access_token'),
        refreshToken: jsonString(map, 'refresh_token'),
      );

  final User user;
  final String accessToken;
  final String refreshToken;
}

class PostModel {
  const PostModel({
    required this.id,
    required this.authorId,
    required this.kind,
    required this.body,
    required this.mediaUrls,
    required this.hashtags,
    required this.likesCount,
    required this.commentsCount,
    required this.createdAt,
    this.gigId,
    this.beforeUrl,
    this.afterUrl,
    this.categoryName,
    this.amountEarned,
    this.rating,
    this.authorName,
    this.authorHandle,
    this.authorAvatar,
    this.authorKarma,
    this.authorTier,
  });

  factory PostModel.fromJson(Map<String, Object?> map) => PostModel(
        id: jsonInt(map, 'id'),
        authorId: jsonInt(map, 'author_id'),
        kind: jsonString(map, 'kind', fallback: 'post'),
        body: jsonString(map, 'body'),
        mediaUrls: jsonStrings(map, 'media_urls'),
        hashtags: jsonStrings(map, 'hashtags'),
        gigId: (map['gig_id'] as num?)?.toInt(),
        beforeUrl: map['before_url'] as String?,
        afterUrl: map['after_url'] as String?,
        categoryName: map['category_name'] as String?,
        amountEarned: (map['amount_earned'] as num?)?.toDouble(),
        rating: (map['rating'] as num?)?.toInt(),
        likesCount: jsonInt(map, 'likes_count'),
        commentsCount: jsonInt(map, 'comments_count'),
        createdAt: _date(map, 'created_at'),
        authorName: map['author_name'] as String?,
        authorHandle: map['author_handle'] as String?,
        authorAvatar: map['author_avatar'] as String?,
        authorKarma: (map['author_karma'] as num?)?.toInt(),
        authorTier: map['author_tier'] as String?,
      );

  final int id;
  final int authorId;
  final String kind;
  final String body;
  final List<String> mediaUrls;
  final List<String> hashtags;
  final int? gigId;
  final String? beforeUrl;
  final String? afterUrl;
  final String? categoryName;
  final double? amountEarned;
  final int? rating;
  final int likesCount;
  final int commentsCount;
  final DateTime createdAt;
  final String? authorName;
  final String? authorHandle;
  final String? authorAvatar;
  final int? authorKarma;
  final String? authorTier;

  bool get isProof => kind == 'proof';

  PostModel copyWith({int? likesCount, int? commentsCount}) => PostModel(
        id: id,
        authorId: authorId,
        kind: kind,
        body: body,
        mediaUrls: mediaUrls,
        hashtags: hashtags,
        gigId: gigId,
        beforeUrl: beforeUrl,
        afterUrl: afterUrl,
        categoryName: categoryName,
        amountEarned: amountEarned,
        rating: rating,
        likesCount: likesCount ?? this.likesCount,
        commentsCount: commentsCount ?? this.commentsCount,
        createdAt: createdAt,
        authorName: authorName,
        authorHandle: authorHandle,
        authorAvatar: authorAvatar,
        authorKarma: authorKarma,
        authorTier: authorTier,
      );

  Map<String, Object?> toJson() => <String, Object?>{
        'id': id,
        'author_id': authorId,
        'kind': kind,
        'body': body,
        'media_urls': mediaUrls,
        'hashtags': hashtags,
        'gig_id': gigId,
        'before_url': beforeUrl,
        'after_url': afterUrl,
        'category_name': categoryName,
        'amount_earned': amountEarned,
        'rating': rating,
        'likes_count': likesCount,
        'comments_count': commentsCount,
        'created_at': createdAt.toIso8601String(),
        'author_name': authorName,
        'author_handle': authorHandle,
        'author_avatar': authorAvatar,
        'author_karma': authorKarma,
        'author_tier': authorTier,
      };
}

class CommentModel {
  const CommentModel({
    required this.id,
    required this.body,
    required this.authorName,
    required this.authorHandle,
    required this.createdAt,
  });

  factory CommentModel.fromJson(Map<String, Object?> map) => CommentModel(
        id: jsonInt(map, 'id'),
        body: jsonString(map, 'body'),
        authorName: jsonString(map, 'author_name'),
        authorHandle: jsonString(map, 'author_handle'),
        createdAt: _date(map, 'created_at'),
      );

  final int id;
  final String body;
  final String authorName;
  final String authorHandle;
  final DateTime createdAt;
}

class ServiceCategory {
  const ServiceCategory({
    required this.id,
    required this.name,
    required this.slug,
    required this.emoji,
    required this.description,
    required this.baseFare,
    required this.perKmRate,
    required this.perHourRate,
    required this.urgencyMultiplier,
    required this.nightMultiplier,
  });

  factory ServiceCategory.fromJson(Map<String, Object?> map) => ServiceCategory(
        id: jsonInt(map, 'id'),
        name: jsonString(map, 'name'),
        slug: jsonString(map, 'slug'),
        emoji: jsonString(map, 'emoji'),
        description: jsonString(map, 'description'),
        baseFare: jsonDouble(map, 'base_fare'),
        perKmRate: jsonDouble(map, 'per_km_rate'),
        perHourRate: jsonDouble(map, 'per_hour_rate'),
        urgencyMultiplier: jsonDouble(map, 'urgency_multiplier', fallback: 1),
        nightMultiplier: jsonDouble(map, 'night_multiplier', fallback: 1),
      );

  final int id;
  final String name;
  final String slug;
  final String emoji;
  final String description;
  final double baseFare;
  final double perKmRate;
  final double perHourRate;
  final double urgencyMultiplier;
  final double nightMultiplier;
}

class FareBreakdown {
  const FareBreakdown({
    required this.baseFare,
    required this.distanceFare,
    required this.timeFare,
    required this.subtotal,
    required this.skillMultiplier,
    required this.urgencyMultiplier,
    required this.nightMultiplier,
    required this.platformFee,
    required this.total,
  });

  factory FareBreakdown.fromJson(Map<String, Object?> map) => FareBreakdown(
        baseFare: jsonDouble(map, 'base_fare'),
        distanceFare: jsonDouble(map, 'distance_fare'),
        timeFare: jsonDouble(map, 'time_fare'),
        subtotal: jsonDouble(map, 'subtotal'),
        skillMultiplier: jsonDouble(map, 'skill_multiplier', fallback: 1),
        urgencyMultiplier: jsonDouble(map, 'urgency_multiplier', fallback: 1),
        nightMultiplier: jsonDouble(map, 'night_multiplier', fallback: 1),
        platformFee: jsonDouble(map, 'platform_fee'),
        total: jsonDouble(map, 'total'),
      );

  final double baseFare;
  final double distanceFare;
  final double timeFare;
  final double subtotal;
  final double skillMultiplier;
  final double urgencyMultiplier;
  final double nightMultiplier;
  final double platformFee;
  final double total;
}

class Candidate {
  const Candidate({
    required this.userId,
    required this.displayName,
    required this.handle,
    required this.rating,
    required this.hourlyRate,
    required this.distanceKm,
    required this.etaMinutes,
    required this.score,
    required this.karma,
    required this.totalJobs,
    required this.verificationTier,
    required this.reasons,
    required this.proofCount,
    this.avatarUrl,
  });

  factory Candidate.fromJson(Map<String, Object?> map) => Candidate(
        userId: jsonInt(map, 'user_id'),
        displayName: jsonString(map, 'display_name'),
        handle: jsonString(map, 'handle'),
        avatarUrl: map['avatar_url'] as String?,
        rating: jsonDouble(map, 'rating'),
        hourlyRate: jsonDouble(map, 'hourly_rate'),
        distanceKm: jsonDouble(map, 'distance_km'),
        etaMinutes: jsonInt(map, 'eta_minutes'),
        score: jsonDouble(map, 'score'),
        karma: jsonInt(map, 'karma'),
        totalJobs: jsonInt(map, 'total_jobs'),
        verificationTier: jsonString(map, 'verification_tier', fallback: 'none'),
        reasons: jsonStrings(map, 'reasons'),
        proofCount: jsonInt(map, 'proof_count'),
      );

  final int userId;
  final String displayName;
  final String handle;
  final String? avatarUrl;
  final double rating;
  final double hourlyRate;
  final double distanceKm;
  final int etaMinutes;
  final double score;
  final int karma;
  final int totalJobs;
  final String verificationTier;
  final List<String> reasons;
  final int proofCount;
}

class GigPayment {
  const GigPayment({
    required this.gigId,
    required this.provider,
    required this.status,
    required this.amount,
    required this.platformFee,
    required this.workerPayout,
    required this.currency,
    required this.paymentIntentId,
    this.clientSecret,
    this.publishableKey,
    this.authorizedAt,
    this.capturedAt,
    this.releasedAt,
    this.refundedAt,
    this.failureMessage,
  });

  factory GigPayment.fromJson(Map<String, Object?> map) => GigPayment(
        gigId: jsonInt(map, 'gig_id'),
        provider: jsonString(map, 'provider'),
        status: jsonString(map, 'status'),
        amount: jsonDouble(map, 'amount'),
        platformFee: jsonDouble(map, 'platform_fee'),
        workerPayout: jsonDouble(map, 'worker_payout'),
        currency: jsonString(map, 'currency', fallback: 'INR'),
        paymentIntentId: jsonString(map, 'payment_intent_id'),
        clientSecret: map['client_secret'] as String?,
        publishableKey: map['publishable_key'] as String?,
        authorizedAt: _optionalDate(map['authorized_at']),
        capturedAt: _optionalDate(map['captured_at']),
        releasedAt: _optionalDate(map['released_at']),
        refundedAt: _optionalDate(map['refunded_at']),
        failureMessage: map['failure_message'] as String?,
      );

  final int gigId;
  final String provider;
  final String status;
  final double amount;
  final double platformFee;
  final double workerPayout;
  final String currency;
  final String paymentIntentId;
  final String? clientSecret;
  final String? publishableKey;
  final DateTime? authorizedAt;
  final DateTime? capturedAt;
  final DateTime? releasedAt;
  final DateTime? refundedAt;
  final String? failureMessage;

  bool get isSecured =>
      status == 'authorized' || status == 'captured' || status == 'paid';
}

DateTime? _optionalDate(Object? value) =>
    value is String ? DateTime.tryParse(value) : null;

class Gig {
  const Gig({
    required this.id,
    required this.customerId,
    required this.categoryId,
    required this.title,
    required this.description,
    required this.status,
    required this.urgency,
    required this.lat,
    required this.lng,
    required this.addressLabel,
    required this.locationSource,
    required this.photos,
    required this.total,
    required this.fareBreakdown,
    required this.proofPhotos,
    required this.paymentStatus,
    required this.createdAt,
    this.workerId,
    this.completedAt,
  });

  factory Gig.fromJson(Map<String, Object?> map) => Gig(
        id: jsonInt(map, 'id'),
        customerId: jsonInt(map, 'customer_id'),
        workerId: (map['worker_id'] as num?)?.toInt(),
        categoryId: jsonInt(map, 'category_id'),
        title: jsonString(map, 'title'),
        description: jsonString(map, 'description'),
        status: jsonString(map, 'status'),
        urgency: jsonString(map, 'urgency', fallback: 'standard'),
        lat: jsonDouble(map, 'lat'),
        lng: jsonDouble(map, 'lng'),
        addressLabel: jsonString(map, 'address_label'),
        locationSource: jsonString(map, 'location_source', fallback: 'provided'),
        photos: jsonStrings(map, 'photos'),
        total: jsonDouble(map, 'total'),
        fareBreakdown: FareBreakdown.fromJson(jsonMap(map['fare_breakdown'])),
        proofPhotos: jsonStrings(map, 'proof_photos'),
        paymentStatus: jsonString(map, 'payment_status'),
        createdAt: _date(map, 'created_at'),
        completedAt: map['completed_at'] is String
            ? DateTime.tryParse(map['completed_at']! as String)
            : null,
      );

  final int id;
  final int customerId;
  final int? workerId;
  final int categoryId;
  final String title;
  final String description;
  final String status;
  final String urgency;
  final double lat;
  final double lng;
  final String addressLabel;
  final String locationSource;
  final List<String> photos;
  final double total;
  final FareBreakdown fareBreakdown;
  final List<String> proofPhotos;
  final String paymentStatus;
  final DateTime createdAt;
  final DateTime? completedAt;

  bool get isActive => status != 'completed' && status != 'cancelled';
}

class GigStats {
  const GigStats({
    required this.gigsTotal,
    required this.gigsCompleted,
    required this.walletBalance,
    required this.lifetimeEarned,
  });

  factory GigStats.fromJson(Map<String, Object?> map) => GigStats(
        gigsTotal: jsonInt(map, 'gigs_total'),
        gigsCompleted: jsonInt(map, 'gigs_completed'),
        walletBalance: jsonDouble(map, 'wallet_balance'),
        lifetimeEarned: jsonDouble(map, 'lifetime_earned'),
      );

  final int gigsTotal;
  final int gigsCompleted;
  final double walletBalance;
  final double lifetimeEarned;
}

class KarmaEvent {
  const KarmaEvent({
    required this.id,
    required this.eventType,
    required this.domain,
    required this.delta,
    required this.reason,
    required this.createdAt,
  });

  factory KarmaEvent.fromJson(Map<String, Object?> map) => KarmaEvent(
        id: jsonInt(map, 'id'),
        eventType: jsonString(map, 'event_type'),
        domain: jsonString(map, 'domain'),
        delta: jsonInt(map, 'delta'),
        reason: jsonString(map, 'reason'),
        createdAt: _date(map, 'created_at'),
      );

  final int id;
  final String eventType;
  final String domain;
  final int delta;
  final String reason;
  final DateTime createdAt;
}

class KarmaLedger {
  const KarmaLedger({
    required this.blended,
    required this.work,
    required this.social,
    required this.band,
    required this.events,
    required this.totalEvents,
    required this.truncated,
  });

  factory KarmaLedger.fromJson(Map<String, Object?> map) => KarmaLedger(
        blended: jsonInt(map, 'blended'),
        work: jsonInt(map, 'work'),
        social: jsonInt(map, 'social'),
        band: jsonString(map, 'band'),
        events: jsonList(map['events'])
            .map((Object? item) => KarmaEvent.fromJson(jsonMap(item)))
            .toList(growable: false),
        totalEvents: jsonInt(map, 'total_events'),
        truncated: jsonBool(map, 'truncated'),
      );

  final int blended;
  final int work;
  final int social;
  final String band;
  final List<KarmaEvent> events;
  final int totalEvents;
  final bool truncated;
}

class WorkerProfile {
  const WorkerProfile({
    required this.hourlyRate,
    required this.rating,
    required this.ratingCount,
    required this.totalJobs,
    required this.isAvailable,
    required this.verificationTier,
    required this.skills,
    required this.proofs,
    this.category,
    this.lat,
    this.lng,
  });

  factory WorkerProfile.fromJson(Map<String, Object?> map) => WorkerProfile(
        category: map['category'] as String?,
        hourlyRate: jsonDouble(map, 'hourly_rate'),
        rating: jsonDouble(map, 'rating'),
        ratingCount: jsonInt(map, 'rating_count'),
        totalJobs: jsonInt(map, 'total_jobs'),
        isAvailable: jsonBool(map, 'is_available'),
        verificationTier: jsonString(map, 'verification_tier', fallback: 'none'),
        lat: (map['lat'] as num?)?.toDouble(),
        lng: (map['lng'] as num?)?.toDouble(),
        skills: jsonStrings(map, 'skills'),
        proofs: map['proofs'] is List
            ? jsonList(map['proofs']).map(jsonMap).toList(growable: false)
            : <Map<String, Object?>>[],
      );

  final String? category;
  final double hourlyRate;
  final double rating;
  final int ratingCount;
  final int totalJobs;
  final bool isAvailable;
  final String verificationTier;
  final double? lat;
  final double? lng;
  final List<String> skills;
  final List<Map<String, Object?>> proofs;
}

class VerificationSubmission {
  const VerificationSubmission({
    required this.id,
    required this.documentType,
    required this.status,
    required this.createdAt,
  });

  factory VerificationSubmission.fromJson(Map<String, Object?> map) =>
      VerificationSubmission(
        id: jsonInt(map, 'id'),
        documentType: jsonString(map, 'document_type'),
        status: jsonString(map, 'status'),
        createdAt: _date(map, 'created_at'),
      );

  final int id;
  final String documentType;
  final String status;
  final DateTime createdAt;
}

class TrustedContact {
  const TrustedContact({
    required this.id,
    required this.name,
    required this.phone,
    required this.relationship,
  });

  factory TrustedContact.fromJson(Map<String, Object?> map) => TrustedContact(
        id: jsonInt(map, 'id'),
        name: jsonString(map, 'name'),
        phone: jsonString(map, 'phone'),
        relationship: jsonString(map, 'relationship'),
      );

  final int id;
  final String name;
  final String phone;
  final String relationship;
}

class AdminAnalytics {
  const AdminAnalytics({
    required this.users,
    required this.workers,
    required this.gigs,
    required this.gigsCompleted,
    required this.posts,
    required this.proofPosts,
    required this.proofPostsFromGigs,
    required this.pendingVerifications,
    required this.openIncidents,
    required this.openDisputes,
    required this.proofRate,
  });

  factory AdminAnalytics.fromJson(Map<String, Object?> map) => AdminAnalytics(
        users: jsonInt(map, 'users'),
        workers: jsonInt(map, 'workers'),
        gigs: jsonInt(map, 'gigs'),
        gigsCompleted: jsonInt(map, 'gigs_completed'),
        posts: jsonInt(map, 'posts'),
        proofPosts: jsonInt(map, 'proof_posts'),
        proofPostsFromGigs: jsonInt(map, 'proof_posts_from_gigs'),
        pendingVerifications: jsonInt(map, 'pending_verifications'),
        openIncidents: jsonInt(map, 'open_incidents'),
        openDisputes: jsonInt(map, 'open_disputes'),
        proofRate: jsonDouble(map, 'proof_rate'),
      );

  final int users;
  final int workers;
  final int gigs;
  final int gigsCompleted;
  final int posts;
  final int proofPosts;
  final int proofPostsFromGigs;
  final int pendingVerifications;
  final int openIncidents;
  final int openDisputes;
  final double proofRate;
}

class AdminVerification {
  const AdminVerification({
    required this.id,
    required this.userId,
    required this.displayName,
    required this.handle,
    required this.documentType,
    required this.documentRef,
    required this.createdAt,
  });

  factory AdminVerification.fromJson(Map<String, Object?> map) =>
      AdminVerification(
        id: jsonInt(map, 'id'),
        userId: jsonInt(map, 'user_id'),
        displayName: jsonString(map, 'display_name'),
        handle: jsonString(map, 'handle'),
        documentType: jsonString(map, 'document_type'),
        documentRef: jsonString(map, 'document_ref'),
        createdAt: _date(map, 'created_at'),
      );

  final int id;
  final int userId;
  final String displayName;
  final String handle;
  final String documentType;
  final String documentRef;
  final DateTime createdAt;
}

class AdminSafetyIncident {
  const AdminSafetyIncident({
    required this.id,
    required this.raisedBy,
    required this.raisedByName,
    required this.raisedByHandle,
    required this.note,
    required this.status,
    required this.createdAt,
    this.againstUserId,
    this.againstUserName,
    this.againstUserHandle,
    this.gigId,
    this.lat,
    this.lng,
  });

  factory AdminSafetyIncident.fromJson(Map<String, Object?> map) =>
      AdminSafetyIncident(
        id: jsonInt(map, 'id'),
        raisedBy: jsonInt(map, 'raised_by'),
        raisedByName: jsonString(map, 'raised_by_name'),
        raisedByHandle: jsonString(map, 'raised_by_handle'),
        againstUserId: (map['against_user_id'] as num?)?.toInt(),
        againstUserName: map['against_user_name'] as String?,
        againstUserHandle: map['against_user_handle'] as String?,
        gigId: (map['gig_id'] as num?)?.toInt(),
        lat: (map['lat'] as num?)?.toDouble(),
        lng: (map['lng'] as num?)?.toDouble(),
        note: jsonString(map, 'note'),
        status: jsonString(map, 'status', fallback: 'open'),
        createdAt: _date(map, 'created_at'),
      );

  final int id;
  final int raisedBy;
  final String raisedByName;
  final String raisedByHandle;
  final int? againstUserId;
  final String? againstUserName;
  final String? againstUserHandle;
  final int? gigId;
  final double? lat;
  final double? lng;
  final String note;
  final String status;
  final DateTime createdAt;

  AdminSafetyIncident copyWith({String? status}) => AdminSafetyIncident(
        id: id,
        raisedBy: raisedBy,
        raisedByName: raisedByName,
        raisedByHandle: raisedByHandle,
        againstUserId: againstUserId,
        againstUserName: againstUserName,
        againstUserHandle: againstUserHandle,
        gigId: gigId,
        lat: lat,
        lng: lng,
        note: note,
        status: status ?? this.status,
        createdAt: createdAt,
      );
}

class AdminDispute {
  const AdminDispute({
    required this.id,
    required this.gigId,
    required this.gigTitle,
    required this.raisedBy,
    required this.raisedByName,
    required this.raisedByHandle,
    required this.reason,
    required this.status,
    required this.createdAt,
  });

  factory AdminDispute.fromJson(Map<String, Object?> map) => AdminDispute(
        id: jsonInt(map, 'id'),
        gigId: jsonInt(map, 'gig_id'),
        gigTitle: jsonString(map, 'gig_title'),
        raisedBy: jsonInt(map, 'raised_by'),
        raisedByName: jsonString(map, 'raised_by_name'),
        raisedByHandle: jsonString(map, 'raised_by_handle'),
        reason: jsonString(map, 'reason'),
        status: jsonString(map, 'status', fallback: 'open'),
        createdAt: _date(map, 'created_at'),
      );

  final int id;
  final int gigId;
  final String gigTitle;
  final int raisedBy;
  final String raisedByName;
  final String raisedByHandle;
  final String reason;
  final String status;
  final DateTime createdAt;

  AdminDispute copyWith({String? status}) => AdminDispute(
        id: id,
        gigId: gigId,
        gigTitle: gigTitle,
        raisedBy: raisedBy,
        raisedByName: raisedByName,
        raisedByHandle: raisedByHandle,
        reason: reason,
        status: status ?? this.status,
        createdAt: createdAt,
      );
}


class BitchatDevice {
  const BitchatDevice({
    required this.deviceId,
    required this.label,
    required this.identityKey,
    required this.prekeysAvailable,
  });

  factory BitchatDevice.fromJson(Map<String, Object?> map) => BitchatDevice(
        deviceId: jsonString(map, 'device_id'),
        label: jsonString(map, 'label', fallback: 'Peer device'),
        identityKey: jsonString(map, 'identity_key'),
        prekeysAvailable: jsonInt(map, 'prekeys_available'),
      );

  final String deviceId;
  final String label;
  final String identityKey;
  final int prekeysAvailable;

  Map<String, Object?> toJson() => <String, Object?>{
        'device_id': deviceId,
        'label': label,
        'identity_key': identityKey,
        'prekeys_available': prekeysAvailable,
      };
}

class BitchatSession {
  const BitchatSession({
    required this.gigId,
    required this.roomId,
    required this.peerAlias,
    required this.canSend,
    required this.peerDevices,
    required this.ttlOptions,
  });

  factory BitchatSession.fromJson(Map<String, Object?> map) => BitchatSession(
        gigId: jsonInt(map, 'gig_id'),
        roomId: jsonString(map, 'room_id'),
        peerAlias: jsonString(map, 'peer_alias', fallback: 'Gig peer'),
        canSend: jsonBool(map, 'can_send'),
        peerDevices: jsonList(map['peer_devices'])
            .map((Object? item) => BitchatDevice.fromJson(jsonMap(item)))
            .toList(growable: false),
        ttlOptions: jsonList(map['ttl_options'])
            .whereType<num>()
            .map((num item) => item.toInt())
            .toList(growable: false),
      );

  final int gigId;
  final String roomId;
  final String peerAlias;
  final bool canSend;
  final List<BitchatDevice> peerDevices;
  final List<int> ttlOptions;

  Map<String, Object?> toJson() => <String, Object?>{
        'gig_id': gigId,
        'room_id': roomId,
        'peer_alias': peerAlias,
        'can_send': canSend,
        'peer_devices': peerDevices
            .map((BitchatDevice item) => item.toJson())
            .toList(growable: false),
        'ttl_options': ttlOptions,
      };
}

class BitchatClaimedPreKey {
  const BitchatClaimedPreKey({
    required this.recipientDeviceId,
    required this.recipientIdentityKey,
    required this.keyId,
    required this.publicKey,
    required this.signature,
  });

  factory BitchatClaimedPreKey.fromJson(Map<String, Object?> map) =>
      BitchatClaimedPreKey(
        recipientDeviceId: jsonString(map, 'recipient_device_id'),
        recipientIdentityKey: jsonString(map, 'recipient_identity_key'),
        keyId: jsonInt(map, 'key_id'),
        publicKey: jsonString(map, 'public_key'),
        signature: jsonString(map, 'signature'),
      );

  final String recipientDeviceId;
  final String recipientIdentityKey;
  final int keyId;
  final String publicKey;
  final String signature;

  Map<String, Object?> toJson() => <String, Object?>{
        'recipient_device_id': recipientDeviceId,
        'recipient_identity_key': recipientIdentityKey,
        'key_id': keyId,
        'public_key': publicKey,
        'signature': signature,
      };
}

class BitchatEnvelope {
  const BitchatEnvelope({
    required this.messageId,
    required this.gigId,
    required this.roomId,
    required this.senderDeviceId,
    required this.senderIdentityKey,
    required this.recipientDeviceId,
    required this.prekeyId,
    required this.ephemeralKey,
    required this.nonce,
    required this.ciphertext,
    required this.mac,
    required this.signature,
    required this.sentAt,
    required this.expiresAt,
    required this.ttlSeconds,
    required this.maxHops,
    required this.transport,
    this.hopCount = 0,
  });

  factory BitchatEnvelope.fromJson(Map<String, Object?> map) => BitchatEnvelope(
        messageId: jsonString(map, 'message_id'),
        gigId: jsonInt(map, 'gig_id'),
        roomId: jsonString(map, 'room_id'),
        senderDeviceId: jsonString(map, 'sender_device_id'),
        senderIdentityKey: jsonString(map, 'sender_identity_key'),
        recipientDeviceId: jsonString(map, 'recipient_device_id'),
        prekeyId: jsonInt(map, 'prekey_id'),
        ephemeralKey: jsonString(map, 'ephemeral_key'),
        nonce: jsonString(map, 'nonce'),
        ciphertext: jsonString(map, 'ciphertext'),
        mac: jsonString(map, 'mac'),
        signature: jsonString(map, 'signature'),
        sentAt: _date(map, 'sent_at'),
        expiresAt: _date(map, 'expires_at'),
        ttlSeconds: jsonInt(map, 'ttl_seconds'),
        hopCount: jsonInt(map, 'hop_count'),
        maxHops: jsonInt(map, 'max_hops', fallback: 3),
        transport: jsonString(map, 'transport', fallback: 'mesh'),
      );

  final String messageId;
  final int gigId;
  final String roomId;
  final String senderDeviceId;
  final String senderIdentityKey;
  final String recipientDeviceId;
  final int prekeyId;
  final String ephemeralKey;
  final String nonce;
  final String ciphertext;
  final String mac;
  final String signature;
  final DateTime sentAt;
  final DateTime expiresAt;
  final int ttlSeconds;
  final int hopCount;
  final int maxHops;
  final String transport;

  bool get isExpired => !expiresAt.isAfter(DateTime.now().toUtc());

  Map<String, Object?> toApiJson() => <String, Object?>{
        'message_id': messageId,
        'room_id': roomId,
        'sender_device_id': senderDeviceId,
        'recipient_device_id': recipientDeviceId,
        'prekey_id': prekeyId,
        'ephemeral_key': ephemeralKey,
        'nonce': nonce,
        'ciphertext': ciphertext,
        'mac': mac,
        'signature': signature,
        'sent_at': sentAt.toUtc().toIso8601String(),
        'ttl_seconds': ttlSeconds,
        'max_hops': maxHops,
        'transport': transport == 'mesh' ? 'hybrid' : transport,
      };

  Map<String, Object?> toMeshJson({int? hops}) => <String, Object?>{
        ...toApiJson(),
        'gig_id': gigId,
        'sender_identity_key': senderIdentityKey,
        'expires_at': expiresAt.toUtc().toIso8601String(),
        'hop_count': hops ?? hopCount,
        'transport': 'mesh',
      };
}

enum BitchatMode {
  server,
  mesh,
  hybrid;

  String get label => switch (this) {
        BitchatMode.server => 'Server',
        BitchatMode.mesh => 'Mesh',
        BitchatMode.hybrid => 'Hybrid',
      };
}

enum BitchatDelivery { sending, server, mesh, hybrid, failed }

class BitchatMessage {
  const BitchatMessage({
    required this.id,
    required this.text,
    required this.sentAt,
    required this.expiresAt,
    required this.isMine,
    required this.delivery,
  });

  factory BitchatMessage.fromJson(Map<String, Object?> map) => BitchatMessage(
        id: jsonString(map, 'id'),
        text: jsonString(map, 'text'),
        sentAt: _date(map, 'sent_at'),
        expiresAt: _date(map, 'expires_at'),
        isMine: jsonBool(map, 'is_mine'),
        delivery: BitchatDelivery.values.firstWhere(
          (BitchatDelivery item) => item.name == jsonString(map, 'delivery'),
          orElse: () => BitchatDelivery.failed,
        ),
      );

  final String id;
  final String text;
  final DateTime sentAt;
  final DateTime expiresAt;
  final bool isMine;
  final BitchatDelivery delivery;

  bool get isExpired => !expiresAt.isAfter(DateTime.now().toUtc());

  BitchatMessage copyWith({BitchatDelivery? delivery}) => BitchatMessage(
        id: id,
        text: text,
        sentAt: sentAt,
        expiresAt: expiresAt,
        isMine: isMine,
        delivery: delivery ?? this.delivery,
      );

  Map<String, Object?> toJson() => <String, Object?>{
        'id': id,
        'text': text,
        'sent_at': sentAt.toUtc().toIso8601String(),
        'expires_at': expiresAt.toUtc().toIso8601String(),
        'is_mine': isMine,
        'delivery': delivery.name,
      };
}

class UploadedMedia {
  const UploadedMedia({
    required this.id,
    required this.purpose,
    required this.url,
    required this.contentType,
    required this.byteSize,
    required this.sha256,
  });

  factory UploadedMedia.fromJson(Map<String, Object?> map) => UploadedMedia(
        id: jsonString(map, 'id'),
        purpose: jsonString(map, 'purpose'),
        url: jsonString(map, 'url'),
        contentType: jsonString(map, 'content_type'),
        byteSize: jsonInt(map, 'byte_size'),
        sha256: jsonString(map, 'sha256'),
      );

  final String id;
  final String purpose;
  final String url;
  final String contentType;
  final int byteSize;
  final String sha256;
}

class GeocodedPlace {
  const GeocodedPlace({
    required this.placeId,
    required this.label,
    required this.lat,
    required this.lng,
    required this.provider,
    required this.attribution,
  });

  factory GeocodedPlace.fromJson(Map<String, Object?> map) => GeocodedPlace(
        placeId: jsonString(map, 'place_id'),
        label: jsonString(map, 'label'),
        lat: jsonDouble(map, 'lat'),
        lng: jsonDouble(map, 'lng'),
        provider: jsonString(map, 'provider'),
        attribution: jsonString(map, 'attribution'),
      );

  final String placeId;
  final String label;
  final double lat;
  final double lng;
  final String provider;
  final String attribution;
}

class SelectedLocation {
  const SelectedLocation({
    required this.lat,
    required this.lng,
    required this.label,
    required this.source,
    required this.consent,
    this.accuracyM,
    this.geocoder,
  });

  final double lat;
  final double lng;
  final String label;
  final String source;
  final bool consent;
  final double? accuracyM;
  final String? geocoder;
}
