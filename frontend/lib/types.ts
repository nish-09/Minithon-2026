export type Urgency = "normal" | "urgent" | "critical";

export interface Privacy {
  relationship_visibility: "me" | "circle" | "nobody";
  location_sharing: "off" | "requests" | "always";
  prefer_trusted_circle: boolean;
  trusted_circle_default_mode: "ask" | "circle" | "community";
  prefer_circle_for_critical: boolean;
  circle_window_override_s: number | null;
  reveal_relationship_to_helpers: boolean;
}

export interface Me {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  role: "user" | "admin";
  avatar_url: string | null;
  email_verified: boolean;
  phone_verified: boolean;
  identity_verified: boolean;
  lat: number | null;
  lng: number | null;
  is_available: boolean;
  created_at: string;
  bio: string;
  availability_schedule: Record<string, string[]>;
  skills: { slug: string; label: string; years_experience: number }[];
  certifications: { slug: string; label: string; verified: boolean }[];
  privacy: Privacy;
  credits: number;
}

export interface Reference {
  categories: { slug: string; label: string; icon: string; default_skills: string[] }[];
  skills: { slug: string; label: string; trust_category: string | null }[];
  certifications: { slug: string; label: string }[];
  relationship_types: { slug: string; label: string; group: "family" | "friends" | "other" }[];
}

export interface HelperPublic {
  id: number;
  name: string;
  avatar_url: string | null;
  identity_verified: boolean;
  trust_score: number | null;
  certifications: string[];
}

export interface Assignment {
  id: number;
  status: string;
  eta_minutes: number | null;
  distance_km: number | null;
  channel: string;
  helper: HelperPublic;
  relationship_label: string;
  lat: number | null;
  lng: number | null;
}

export interface HelpRequest {
  id: number;
  title: string;
  description: string;
  raw_text: string | null;
  category: string;
  category_label: string;
  icon: string;
  urgency: Urgency;
  status: string;
  skills_required: string[];
  num_helpers: number;
  filled_slots: number;
  time_requirement: string | null;
  lat: number | null;
  lng: number | null;
  location_approximate: boolean;
  location_shared: boolean;
  distance_km: number | null;
  routing_mode: string;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
  viewer_role: "requester" | "helper" | "recipient" | "admin" | null;
  incident_id: number | null;
  nlu_source: string;
  requester: { id: number; name: string; avatar_url: string | null } | null;
  circle_deadline: string | null;
  assignments?: Assignment[];
  recipients?: { user_id: number; name: string | null; channel: string; state: string; match_score: number | null }[];
  history?: { from: string | null; to: string; note: string | null; at: string }[];
  reviews?: { helper_id: number; rating: number }[];
  my_assignment?: { id: number; status: string; eta_minutes: number | null; distance_km: number | null };
  my_recipient_state?: string;
  channel?: string;
  can_accept?: boolean;
  relationship_label?: string | null;
}

export interface Understanding {
  intent: string;
  category: string;
  urgency: Urgency;
  description: string;
  title: string;
  skills_required: string[];
  time_requirement: string | null;
  num_helpers: number;
  location_required: boolean;
  context: Record<string, unknown>;
  confidence: number;
  source: "rules" | "llm";
}

export interface CircleSummary {
  count: number;
  groups: Record<string, number>;
  phrase: string;
  members: { id: number; name: string; distance_km: number | null; available: boolean }[];
}

export interface UnderstandResponse {
  understanding: Understanding;
  circle_window_s: number;
  trusted_circle: CircleSummary;
  circle_prompt: string | null;
  suggested_routing: "emergency" | "circle_first" | "community";
  emergency_advice: string | null;
}

export interface RelationshipEdge {
  id: number;
  user: { id: number; name: string; avatar_url: string | null; identity_verified: boolean };
  relationship_type: string;
  label: string;
  group: "family" | "friends" | "other";
  status: "PENDING" | "ACCEPTED" | "DECLINED" | "BLOCKED";
  direction: "incoming" | "outgoing";
  can_respond: boolean;
  is_trusted: boolean;
  can_receive_requests: boolean;
  visibility: "me" | "circle" | "nobody";
  priority: number;
  distance_km: number | null;
  eta_minutes: number | null;
  available: boolean | null;
  contactable?: boolean;
  nearby?: boolean;
}

export interface TrustedCircle {
  groups: { family: RelationshipEdge[]; friends: RelationshipEdge[]; other: RelationshipEdge[] };
  nearby_count: number;
  total: number;
  pending: RelationshipEdge[];
}

export interface TrustCardData {
  user_id: number;
  name: string;
  avatar_url: string | null;
  score: number;
  confidence: number;
  model_version: string;
  components: { key: string; label: string; score: number; weight: number }[];
  categories: { category: string; label: string; score: number }[];
  factors: { key: string; label: string; impact: "positive" | "negative" | "neutral"; detail: string }[];
  badges: string[];
  stats: {
    response_rate: number | null;
    acceptance_rate: number | null;
    cancellation_rate: number | null;
    no_show_rate: number | null;
    avg_response_seconds: number | null;
    completed: number;
    rating: number | null;
    review_count: number;
  };
  certifications: string[];
  disclaimer: string;
}

export interface MatchResult {
  helper: HelperPublic;
  match_score: number;
  trust_score: number;
  category_trust: number | null;
  distance_km: number;
  eta_minutes: number;
  in_circle: boolean;
  relationship_priority: number | null;
  relationship_label: string;
  reasons: string[];
  skills_matched: string[];
  breakdown: Record<string, number>;
}

export interface IncidentState {
  incident_id: string;
  id: number;
  status: "ACTIVE" | "RESOLVED" | "CANCELLED";
  urgency: string;
  location_shared: boolean;
  situation: string;
  user_responsive: boolean;
  current_protocol: string | null;
  protocol_title: string | null;
  protocol_version: number | null;
  current_step: number;
  total_steps: number;
  completed_steps: number[];
  skipped_steps: number[];
  current_instruction: string | null;
  protocol_finished: boolean;
  assigned_helper: string | null;
  assigned_helper_name: string | null;
  helper_eta_minutes: number | null;
  helper_arrived: boolean;
  emergency_services_advised: boolean;
  emergency_services_contacted: boolean;
  emergency_number: string;
  escalation_level: number;
  care_active: boolean;
  request_id: number | null;
  started_at: string | null;
  disclaimer: string;
}

export interface CareReply {
  speech: string;
  incident: IncidentState;
  actions: string[];
}

export interface VoiceResult {
  speech: string;
  context: { stage?: "awaiting_circle_choice" | "awaiting_cancel_confirm"; draft_text?: string; request_id?: number };
  actions: string[];
  data: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
}

export interface NotificationItem {
  id: number;
  kind: string;
  title: string;
  body: string;
  data: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  read: boolean;
  created_at: string;
}

export interface Review {
  id: number;
  rating: number;
  comment: string;
  category: string | null;
  created_at: string;
  reviewer: string;
}

export interface RadarItem {
  id: number;
  category: string;
  icon: string;
  label: string;
  urgency: Urgency;
  lat: number;
  lng: number;
  distance_km: number;
  status: string;
  invited: boolean;
  created_at: string;
}

export interface HelperMarker {
  id: number;
  lat: number;
  lng: number;
  distance_km: number;
  trust_score: number | null;
  skills: string[];
  verified: boolean;
}

export interface DirectoryItem {
  id: number;
  name: string;
  category: string;
  phone: string | null;
  address: string | null;
  lat: number | null;
  lng: number | null;
  is_24h: boolean;
  notes: string | null;
  distance_km: number | null;
}

export interface CommunityEventItem {
  id: number;
  title: string;
  description: string;
  lat: number;
  lng: number;
  starts_at: string;
  distance_km: number | null;
}

export interface Dashboard {
  active_requests: number;
  urgent_requests: number;
  critical_incidents: number;
  helpers_online: number;
  helpers_connected: number;
  unmatched_requests: number;
  completed_today: number;
  avg_response_seconds: number | null;
  open_reports: number;
}

export interface Analytics {
  days: number;
  total_requests: number;
  categories: { category: string; label: string; count: number; unmatched: number }[];
  urgency: Record<string, number>;
  requests_per_day: [string, number][];
  response_time: { count: number; median_s: number | null; p90_s: number | null };
  volunteer_availability: Record<string, number>;
  urgent_incidents: number;
  resource_gaps: { category: string; label: string; requests: number; available_helpers: number; ratio: number }[];
  heatmap: { lat: number; lng: number; weight: number; count: number }[];
}

export type ListingKind = "sell" | "gift" | "service";

export interface ListingClaimItem {
  id: number;
  user: { id: number; name: string; verified: boolean };
  message: string;
  status: "pending" | "accepted" | "declined" | "withdrawn";
  created_at: string;
}

export interface Listing {
  id: number;
  kind: ListingKind;
  category: string;
  title: string;
  description: string;
  price: number | null;
  condition: string | null;
  status: "available" | "reserved" | "closed";
  created_at: string;
  distance_km: number | null;
  owner: { id: number; name: string; verified: boolean };
  is_mine: boolean;
  contact_phone: string | null;
  my_claim: { id: number; status: string } | null;
  reserved_for_me: boolean;
  claim_count: number | null;
  claims?: ListingClaimItem[];
}
