/** API contracts. These mirror the Pydantic schemas on the backend exactly. */

export type User = {
  id: number
  uuid: string
  handle: string
  display_name: string
  email: string | null
  phone: string | null
  avatar_url: string | null
  bio: string
  city: string | null
  capabilities: string[]
  is_verified: boolean
  verification_tier: string
  karma: number
  karma_work: number
  karma_social: number
  streak: number
  followers_count: number
  following_count: number
  posts_count: number
  status_text: string | null
}

export type AuthResponse = {
  user: User
  access_token: string
  refresh_token: string
  token_type: string
}

export type TokenPair = { access_token: string; refresh_token: string }

export type KarmaEvent = {
  id: number
  event_type: string
  domain: 'trust' | 'work' | 'social' | 'migration'
  delta: number
  reason: string
  created_at: string
}

export type KarmaLedger = {
  blended: number
  work: number
  social: number
  band: 'dormant' | 'building' | 'trusted' | 'proven'
  /** One bounded page of history. */
  events: KarmaEvent[]
  /** The true row count — `events` may be a truncated page. */
  total_events: number
  truncated: boolean
}

export type Category = {
  id: number
  name: string
  slug: string
  emoji: string
  description: string
  base_fare: number
  per_km_rate: number
  per_hour_rate: number
  urgency_multiplier: number
  night_multiplier: number
}

export type FareBreakdown = {
  base_fare: number
  distance_fare: number
  time_fare: number
  subtotal: number
  skill_multiplier: number
  urgency_multiplier: number
  night_multiplier: number
  platform_fee: number
  total: number
}

export type GeocodedPlace = {
  place_id: string
  label: string
  lat: number
  lng: number
  provider: string
  attribution: string
}

export type Candidate = {
  user_id: number
  display_name: string
  handle: string
  avatar_url: string | null
  rating: number
  hourly_rate: number
  distance_km: number
  eta_minutes: number
  score: number
  karma: number
  total_jobs: number
  verification_tier: string
  reasons: string[]
  proof_count: number
}

export type Gig = {
  id: number
  customer_id: number
  worker_id: number | null
  category_id: number
  title: string
  description: string
  status:
    | 'searching'
    | 'assigned'
    | 'en_route'
    | 'arrived'
    | 'in_progress'
    | 'completion_pending'
    | 'completed'
    | 'cancelled'
  urgency: 'standard' | 'urgent'
  lat: number
  lng: number
  address_label: string
  location_source: 'device' | 'geocoded' | 'provided'
  location_accuracy_m: number | null
  geocoder: string | null
  total: number
  fare_breakdown: FareBreakdown
  photos: string[]
  proof_photos: string[]
  payment_status: string
  created_at: string
  completed_at: string | null
}

export type GigPayment = {
  gig_id: number
  provider: 'stripe' | 'simulated'
  status: string
  amount: number
  platform_fee: number
  worker_payout: number
  currency: string
  payment_intent_id: string
  client_secret: string | null
  publishable_key: string | null
  authorized_at: string | null
  captured_at: string | null
  released_at: string | null
  refunded_at: string | null
  failure_message: string | null
}

export type Post = {
  id: number
  author_id: number
  kind: 'post' | 'reel' | 'pulse' | 'proof'
  body: string
  media_urls: string[]
  hashtags: string[]
  gig_id: number | null
  before_url: string | null
  after_url: string | null
  category_name: string | null
  amount_earned: number | null
  rating: number | null
  likes_count: number
  comments_count: number
  created_at: string
  author_name: string | null
  author_handle: string | null
  author_avatar: string | null
  author_karma: number | null
  author_tier: string | null
}

/** The shape `/workers/me/profile` actually returns. */
export type MyWorkerProfile = {
  category: string | null
  hourly_rate: number
  rating: number
  rating_count: number
  total_jobs: number
  is_available: boolean
  verification_tier: string
  lat: number | null
  lng: number | null
  location_source: string | null
  location_accuracy_m: number | null
  location_updated_at: string | null
  skills: string[]
}

export type Stats = {
  gigs_total: number
  gigs_completed: number
  wallet_balance: number
  lifetime_earned: number
}

export type Verification = {
  id: number
  document_type: string
  status: string
  created_at: string
}

export type TrustedContact = {
  id: number
  name: string
  phone: string
  relationship: string
}

export type Review = {
  id: number
  gig_id: number
  reviewer_id: number
  reviewee_id: number
  rating: number
  comment: string
  created_at: string
}
