export interface VisibleGraphNode {
  id: string;
  type: string;
  label: string;
}

export interface VisibleGraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
}

export interface RelationshipPath {
  nodes: VisibleGraphNode[];
  edges: VisibleGraphEdge[];
}

interface AdjacentEdge {
  edge: VisibleGraphEdge;
  neighborId: string;
}

function stableCompare(left: string, right: string): number {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

export function findRelationshipPath(
  nodes: VisibleGraphNode[],
  edges: VisibleGraphEdge[],
  startId: string,
  targetId: string,
  maxDepth = Math.max(0, nodes.length - 1),
): RelationshipPath | null {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  if (!nodesById.has(startId) || !nodesById.has(targetId)) return null;
  if (startId === targetId) return { nodes: [nodesById.get(startId)!], edges: [] };

  const adjacency = new Map<string, AdjacentEdge[]>();
  for (const node of nodes) adjacency.set(node.id, []);
  for (const edge of edges) {
    if (!nodesById.has(edge.source) || !nodesById.has(edge.target)) continue;
    adjacency.get(edge.source)!.push({ edge, neighborId: edge.target });
    adjacency.get(edge.target)!.push({ edge, neighborId: edge.source });
  }
  for (const neighbors of adjacency.values()) {
    neighbors.sort(
      (left, right) =>
        stableCompare(left.neighborId, right.neighborId) ||
        stableCompare(left.edge.type, right.edge.type) ||
        stableCompare(left.edge.id, right.edge.id),
    );
  }

  const boundedDepth = Math.max(0, Math.floor(maxDepth));
  const queue: Array<{ id: string; depth: number }> = [{ id: startId, depth: 0 }];
  const visited = new Set([startId]);
  const previous = new Map<string, { nodeId: string; edge: VisibleGraphEdge }>();

  for (let index = 0; index < queue.length; index += 1) {
    const current = queue[index];
    if (current.depth >= boundedDepth) continue;
    for (const adjacent of adjacency.get(current.id) ?? []) {
      if (visited.has(adjacent.neighborId)) continue;
      visited.add(adjacent.neighborId);
      previous.set(adjacent.neighborId, { nodeId: current.id, edge: adjacent.edge });
      if (adjacent.neighborId === targetId) {
        const pathNodes: VisibleGraphNode[] = [nodesById.get(targetId)!];
        const pathEdges: VisibleGraphEdge[] = [];
        let cursor = targetId;
        while (cursor !== startId) {
          const parent = previous.get(cursor)!;
          pathEdges.push(parent.edge);
          cursor = parent.nodeId;
          pathNodes.push(nodesById.get(cursor)!);
        }
        return { nodes: pathNodes.reverse(), edges: pathEdges.reverse() };
      }
      queue.push({ id: adjacent.neighborId, depth: current.depth + 1 });
    }
  }

  return null;
}

export function relationshipStepLabel(
  edge: VisibleGraphEdge,
  from: VisibleGraphNode,
  to: VisibleGraphNode,
): string {
  const forward = edge.source === from.id && edge.target === to.id;
  if (edge.type === "INVOLVES") return forward ? "involves" : "involved in payment";
  if (edge.type === "SEEN_ON") {
    return forward ? "instrument observed on device" : "device observed with instrument";
  }
  if (edge.type === "USES") {
    const otherType = forward ? to.type : from.type;
    if (!forward) {
      if (from.type === "DEVICE") return "device used by customer";
      if (from.type === "PAYMENT_INSTRUMENT") return "instrument used by customer";
      if (from.type === "IP_ADDRESS") return "IP observed with customer";
      if (from.type === "ADDRESS") return "address used by customer";
      return "used by customer";
    }
    if (otherType === "DEVICE") return "used device";
    if (otherType === "PAYMENT_INSTRUMENT") return "used payment instrument";
    if (otherType === "IP_ADDRESS") return "observed from IP";
    if (otherType === "ADDRESS") return "used address";
  }
  return edge.type.replaceAll("_", " ").toLowerCase();
}

export function relationshipPathInterpretation(path: RelationshipPath): string {
  const types = path.nodes.map((node) => node.type);
  const customerCount = types.filter((type) => type === "CUSTOMER").length;
  if (types.includes("DEVICE") && customerCount > 1) {
    return "These identities are connected through shared device infrastructure.";
  }
  if (types.includes("DEVICE")) {
    return "This path connects the selected entities through observed device usage.";
  }
  if (types.includes("PAYMENT_INSTRUMENT")) {
    return "This path connects the selected entities through observed payment-instrument usage.";
  }
  if (types.includes("IP_ADDRESS")) {
    return "This path connects the selected entities through observed network access.";
  }
  if (types.includes("ADDRESS")) {
    return "This path connects the selected entities through observed address usage.";
  }
  return "The visible relationships above connect the selected entities.";
}
