from statistics import median

from ml.training.dataset import AssembledDataset


def graph_cluster_ring_matching(
    dataset: AssembledDataset, test_indices: list[int], overlap_threshold: float = 0.5
) -> dict[str, object]:
    test_entities = {
        entity for index in test_indices for entity in dataset.graph_transactions[index].entities()
    }
    rings: dict[str, set[object]] = {}
    for index in test_indices:
        item = dataset.metadata[index]
        if item.ring_id:
            rings.setdefault(item.ring_id, set()).update(
                dataset.graph_transactions[index].entities()
            )
    clusters = [set(cluster.members) & test_entities for cluster in dataset.clusters]
    clusters = [members for members in clusters if members]
    best_overlaps: list[float] = []
    for ring_members in rings.values():
        best_overlaps.append(
            max(
                (
                    len(ring_members & cluster_members) / len(ring_members | cluster_members)
                    for cluster_members in clusters
                ),
                default=0.0,
            )
        )
    return {
        "metric": "typed_entity_jaccard_restricted_to_test_entities",
        "overlap_threshold": overlap_threshold,
        "ground_truth_rings_in_test": len(rings),
        "discovered_clusters_touching_test": len(clusters),
        "rings_above_threshold": sum(value >= overlap_threshold for value in best_overlaps),
        "median_best_overlap": float(median(best_overlaps)) if best_overlaps else 0.0,
    }
