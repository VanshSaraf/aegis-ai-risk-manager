const signalTitles: Record<string, string> = {
  DEVICE_MULTI_CUSTOMER_CONCENTRATION: "One device, multiple customer identities",
  DEVICE_MULTI_INSTRUMENT_CONCENTRATION: "One device, multiple payment instruments",
  RAPID_RELATIONSHIP_EXPANSION: "Relationships expanding rapidly",
  DENSE_MULTI_ENTITY_STRUCTURE: "Dense shared infrastructure",
};

export function humanizeSignal(code: string, fallback?: string): string {
  const normalized = code.replace(/^GRAPH_SIGNAL_/, "");
  return signalTitles[normalized] ?? fallback ?? normalized.replaceAll("_", " ");
}

export function technicalSignalCode(code: string): string {
  return code.replace(/^GRAPH_SIGNAL_/, "");
}

export function humanizeNodeType(type: string): string {
  if (type === "PAYMENT_INSTRUMENT") return "Payment instrument";
  if (type === "IP_ADDRESS") return "IP address";
  return type.charAt(0) + type.slice(1).toLowerCase().replaceAll("_", " ");
}
