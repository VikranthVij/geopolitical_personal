import time
from app.feature6 import candidate_pairs, assess_pair, _importance


def run_benchmark():
    results = {}
    for n in (100, 500, 1000):
        # Generate n claims across a variety of claim types
        claims = []
        for i in range(n):
            kind = ["QUANTITATIVE", "STATUS", "LOCATION", "TIME", "INTENT", "OCCURRENCE", "ATTRIBUTION", "CONSEQUENCE"][i % 8]
            claims.append({
                "id": f"claim-{i}",
                "incident_id": "inc-bench-1",
                "type": kind,
                "statement": f"Statement for claim {i} in incident",
                "normalized_representation": {
                    "quantity": {"operator": "EQ", "value": i, "unit": "missiles", "original": f"{i} missiles"} if kind == "QUANTITATIVE" else None,
                    "target": "base" if kind in {"STATUS", "ATTRIBUTION"} else None,
                    "location_text": "City A" if kind == "LOCATION" else None,
                    "normalized": f"10:{i % 60:02d}UTC" if kind == "TIME" else None,
                    "precision": "MINUTE" if kind == "TIME" else None,
                    "intent_expression": "deterrence" if kind == "INTENT" else None,
                    "predicate_surface": "strike" if kind == "OCCURRENCE" else None,
                    "actor": f"Actor {i % 3}" if kind == "ATTRIBUTION" else None,
                },
                "polarity": "AFFIRMED" if i % 2 == 0 else "NEGATED",
                "intent_label": "REPORTED_INTENT" if kind == "INTENT" else None,
            })

        # 1. Candidate generation
        t0 = time.perf_counter()
        pairs = candidate_pairs(claims, per_claim=20, total_limit=5000)
        t_cand = (time.perf_counter() - t0) * 1000

        # 2. Pairwise contradiction resolution
        t0 = time.perf_counter()
        assessments = [assess_pair(a, b) for a, b in pairs]
        t_assess = (time.perf_counter() - t0) * 1000

        # 3. Importance calculation
        t0 = time.perf_counter()
        _importance("Massive military missile strike on energy and shipping infrastructure with civilian casualties", incident_count=5)
        t_imp = (time.perf_counter() - t0) * 1000

        results[n] = {
            "pairs_generated": len(pairs),
            "candidate_generation_ms": round(t_cand, 2),
            "contradiction_resolution_ms": round(t_assess, 2),
            "importance_calculation_ms": round(t_imp, 3),
            "total_cpu_ms": round(t_cand + t_assess + t_imp, 2),
        }
        print(f"[{n} claims] Pairs: {len(pairs)}, Candidate gen: {t_cand:.2f}ms, Assessment: {t_assess:.2f}ms, Importance: {t_imp:.3f}ms | Total CPU: {t_cand + t_assess + t_imp:.2f}ms")

    return results


if __name__ == "__main__":
    run_benchmark()
