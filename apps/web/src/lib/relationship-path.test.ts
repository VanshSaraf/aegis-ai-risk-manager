import assert from "node:assert/strict";
import test from "node:test";

import {
  findRelationshipPath,
  type VisibleGraphEdge,
  type VisibleGraphNode,
} from "./relationship-path";

const nodes: VisibleGraphNode[] = ["a", "b", "c", "d"].map((id) => ({
  id,
  type: "CUSTOMER",
  label: id.toUpperCase(),
}));

function edge(id: string, source: string, target: string): VisibleGraphEdge {
  return { id, source, target, type: "USES" };
}

test("returns a direct connection", () => {
  const path = findRelationshipPath(nodes, [edge("ab", "a", "b")], "a", "b");
  assert.deepEqual(path?.nodes.map((node) => node.id), ["a", "b"]);
  assert.deepEqual(path?.edges.map((item) => item.id), ["ab"]);
});

test("returns a multi-hop connection", () => {
  const path = findRelationshipPath(
    nodes,
    [edge("ab", "a", "b"), edge("bc", "b", "c"), edge("cd", "c", "d")],
    "a",
    "d",
  );
  assert.deepEqual(path?.nodes.map((node) => node.id), ["a", "b", "c", "d"]);
});

test("chooses equal-length paths by stable neighbor ordering", () => {
  const path = findRelationshipPath(
    nodes,
    [edge("cd", "c", "d"), edge("ac", "a", "c"), edge("bd", "b", "d"), edge("ab", "a", "b")],
    "a",
    "d",
  );
  assert.deepEqual(path?.nodes.map((node) => node.id), ["a", "b", "d"]);
});

test("returns null for disconnected and empty graphs", () => {
  assert.equal(findRelationshipPath(nodes, [edge("ab", "a", "b")], "a", "d"), null);
  assert.equal(findRelationshipPath([], [], "a", "b"), null);
});

test("never traverses beyond the supplied visible-depth bound", () => {
  const edges = [edge("ab", "a", "b"), edge("bc", "b", "c")];
  assert.equal(findRelationshipPath(nodes, edges, "a", "c", 1), null);
  assert.deepEqual(
    findRelationshipPath(nodes, edges, "a", "c", 2)?.nodes.map((node) => node.id),
    ["a", "b", "c"],
  );
});
