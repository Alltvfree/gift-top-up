import {
  supabase,
  type BotRow,
  type BrokerAccountRow,
  type PositionRow,
  type PresetRow,
} from "@/lib/supabase";

export async function fetchBots(): Promise<BotRow[]> {
  const { data, error } = await supabase
    .from("bots")
    .select("*")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data ?? []) as BotRow[];
}

export async function createBot(input: {
  name: string;
  strategy: "GRID" | "DCA";
  symbol: string;
  parameters: Record<string, unknown>;
  ai_preset_used: string | null;
  broker_account_id?: string | null;
}): Promise<BotRow> {
  const { data: userData } = await supabase.auth.getUser();
  const userId = userData.user?.id;
  const { data, error } = await supabase
    .from("bots")
    .insert({ ...input, user_id: userId })
    .select()
    .single();
  if (error) throw error;
  return data as BotRow;
}

export async function setBotStatus(
  id: string,
  status: "running" | "stopped",
): Promise<void> {
  const patch: Record<string, unknown> =
    status === "running"
      ? { status, started_at: new Date().toISOString(), stopped_at: null }
      : { status, stopped_at: new Date().toISOString() };
  const { error } = await supabase.from("bots").update(patch).eq("id", id);
  if (error) throw error;
}

export async function deleteBot(id: string): Promise<void> {
  const { error } = await supabase.from("bots").delete().eq("id", id);
  if (error) throw error;
}

export async function fetchPositions(): Promise<PositionRow[]> {
  const { data, error } = await supabase
    .from("positions")
    .select("*")
    .is("closed_at", null)
    .order("opened_at", { ascending: false });
  if (error) throw error;
  return (data ?? []) as PositionRow[];
}

export async function fetchClosedPositions(limit = 200): Promise<PositionRow[]> {
  const { data, error } = await supabase
    .from("positions")
    .select("*")
    .not("closed_at", "is", null)
    .order("closed_at", { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as PositionRow[];
}

export async function fetchBrokerAccounts(): Promise<BrokerAccountRow[]> {
  const { data, error } = await supabase
    .from("broker_accounts")
    .select("*")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data ?? []) as BrokerAccountRow[];
}

export async function fetchPresets(): Promise<PresetRow[]> {
  const { data, error } = await supabase
    .from("ai_presets")
    .select("*")
    .order("risk_level", { ascending: true });
  if (error) throw error;
  return (data ?? []) as PresetRow[];
}
