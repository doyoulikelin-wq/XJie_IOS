"""Deterministic demo data for omics panels (proteomics/metabolomics/genomics/microbiome).

Strategy: hash user_id to a seed so each user always sees the same values.
All values are within published reference ranges but shifted by mild noise
to feel "real". Values are realistic but explicitly marked is_demo=true in
responses to satisfy regulatory/UX transparency.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field


def _seed_for(user_id: int) -> int:
    h = hashlib.sha256(f"xjie-omics-demo-v1:{user_id}".encode()).hexdigest()
    return int(h[:16], 16)


@dataclass
class DemoItem:
    name: str
    key: str
    value: float
    unit: str
    status: str  # normal | high | low | borderline
    reference: str  # e.g. "40-120 umol/L"
    story_zh: str  # one-line consumer-friendly interpretation
    relevance: list[str] = field(default_factory=list)  # tags like cgm/heart/t2d


def _status(v: float, lo: float, hi: float, hard_margin: float = 0.15) -> str:
    span = hi - lo
    if v < lo - span * hard_margin:
        return "low"
    if v > hi + span * hard_margin:
        return "high"
    if v < lo or v > hi:
        return "borderline"
    return "normal"


# ── Metabolomics (20 key analytes) ─────────────────────────────
_METAB_DEFS = [
    ("BCAA (支链氨基酸)", "bcaa", 360, 680, "μmol/L", ["cgm", "t2d"], "BCAA 反映胰岛素敏感性，升高提示胰岛素抵抗早期信号"),
    ("TMAO (氧化三甲胺)", "tmao", 1.5, 6.0, "μmol/L", ["heart"], "TMAO 由肠道菌群代谢产生，持续升高与动脉粥样硬化风险相关"),
    ("Bile Acids (胆汁酸)", "bile_acids", 1.0, 10.0, "μmol/L", ["cgm", "liver"], "胆汁酸参与脂肪消化与血糖调节"),
    ("Ceramides (神经酰胺)", "ceramides", 120, 280, "nmol/L", ["heart"], "神经酰胺是心血管事件的独立预测标志物"),
    ("Kynurenine/Tryptophan", "kyn_trp", 0.025, 0.055, "ratio", ["mood"], "色氨酸分流比，升高与慢性炎症/情绪低落相关"),
    ("Acylcarnitines C3:0", "c3_acyl", 0.2, 0.6, "μmol/L", ["t2d"], "中链酰基肉碱，反映脂肪酸氧化效率"),
    ("Lactate (乳酸)", "lactate", 0.5, 2.2, "mmol/L", ["cgm"], "静息乳酸升高提示线粒体代谢压力"),
    ("Pyruvate (丙酮酸)", "pyruvate", 40, 120, "μmol/L", ["cgm"], "糖代谢枢纽，反映有氧代谢状态"),
    ("GlycA (糖蛋白信号)", "glyca", 320, 400, "μmol/L", ["inflammation"], "慢性低度炎症综合指标，比 hs-CRP 更稳定"),
    ("Alpha-hydroxybutyrate", "ahb", 2.0, 5.5, "mg/L", ["t2d"], "胰岛素抵抗早期标志物，常在空腹血糖异常前 2-3 年出现"),
    ("Glycerol (甘油)", "glycerol", 30, 120, "μmol/L", ["t2d"], "脂肪分解产物，反映脂肪动员"),
    ("Citrate (柠檬酸)", "citrate", 80, 200, "μmol/L", ["heart"], "TCA 循环关键中间体"),
    ("Uric Acid (尿酸)", "uric_acid", 210, 420, "μmol/L", ["heart", "inflammation"], "升高与高血压、心血管疾病相关"),
    ("Phospholipids Total", "phospholipids", 2.0, 3.5, "mmol/L", ["heart"], "磷脂总量反映脂代谢健康"),
    ("ApoB/ApoA1 Ratio", "apob_apoa1", 0.45, 0.85, "ratio", ["heart"], "动脉粥样硬化指数，比 LDL 更精准"),
    ("Sphingomyelin", "sphingomyelin", 0.4, 0.7, "mmol/L", ["heart"], "鞘磷脂，膜结构与信号传导"),
    ("Glutamine", "glutamine", 500, 750, "μmol/L", ["t2d"], "最丰富的氨基酸，保护胰岛功能"),
    ("Glycine", "glycine", 200, 350, "μmol/L", ["t2d"], "升高提示胰岛素敏感性较好"),
    ("Histidine", "histidine", 70, 110, "μmol/L", ["inflammation"], "抗氧化氨基酸，下降与炎症负担相关"),
    ("Tyrosine", "tyrosine", 50, 100, "μmol/L", ["t2d"], "升高与胰岛素抵抗关联"),
]


# ── Proteomics (12 proteins) ───────────────────────────────────
_PROT_DEFS = [
    ("CRP (C-反应蛋白)", "crp", 0.2, 3.0, "mg/L", ["inflammation"], "急性期蛋白，反映全身炎症"),
    ("IL-6", "il6", 0.5, 3.5, "pg/mL", ["inflammation"], "核心促炎细胞因子"),
    ("TNF-α", "tnf_alpha", 1.0, 8.5, "pg/mL", ["inflammation"], "肿瘤坏死因子，代谢性炎症核心"),
    ("Adiponectin", "adiponectin", 4.0, 18.0, "μg/mL", ["t2d", "heart"], "降低与胰岛素抵抗、心血管风险相关"),
    ("Leptin", "leptin", 3.0, 18.0, "ng/mL", ["t2d"], "饱食信号，肥胖人群常见抵抗"),
    ("FGF21", "fgf21", 60, 300, "pg/mL", ["t2d", "liver"], "肝脏应激标志物，MASLD 早期升高"),
    ("ApoA1", "apoa1", 1.2, 1.8, "g/L", ["heart"], "HDL 载体蛋白，高值保护心血管"),
    ("ApoB", "apob", 0.5, 1.0, "g/L", ["heart"], "LDL 颗粒数指示物"),
    ("Lp(a)", "lpa", 0, 30, "mg/dL", ["heart"], "遗传性心血管危险因子"),
    ("hs-cTnI", "hs_tni", 0, 11, "ng/L", ["heart"], "心肌高敏肌钙蛋白"),
    ("NT-proBNP", "nt_probnp", 0, 125, "pg/mL", ["heart"], "心衰早期指标"),
    ("GDF-15", "gdf15", 200, 1200, "pg/mL", ["aging", "heart"], "整体代谢压力/衰老标志"),
]


# ── Genomics (8 SNP tendencies) ────────────────────────────────
# (name, key, risk_alleles_prob, genotype_labels, relevance, story)
_GENE_DEFS = [
    ("TCF7L2 (rs7903146)", "tcf7l2", [0.25, 0.50, 0.25], ["CC (基准)", "CT (中等)", "TT (较高)"], ["t2d"],
     "世界最强 2 型糖尿病遗传易感位点"),
    ("FTO (rs9939609)", "fto", [0.40, 0.45, 0.15], ["TT (基准)", "AT (中等)", "AA (较高)"], ["obesity"],
     "肥胖易感基因，影响食欲调节"),
    ("APOE (rs429358/rs7412)", "apoe", [0.08, 0.60, 0.20, 0.10, 0.02], ["ε2/ε2", "ε3/ε3", "ε3/ε4", "ε2/ε4", "ε4/ε4"], ["heart"],
     "脂代谢与血管健康遗传组合"),
    ("MTHFR (C677T)", "mthfr", [0.45, 0.40, 0.15], ["CC", "CT", "TT"], ["heart"], "叶酸代谢/同型半胱氨酸"),
    ("PPARG (Pro12Ala)", "pparg", [0.85, 0.14, 0.01], ["Pro/Pro", "Pro/Ala", "Ala/Ala"], ["t2d"],
     "Ala 等位基因保护型，胰岛素敏感性较好"),
    ("SLC22A1 (metformin)", "slc22a1", [0.65, 0.30, 0.05], ["GG", "GA", "AA"], ["drug"], "二甲双胍代谢效率"),
    ("PNPLA3 (rs738409)", "pnpla3", [0.55, 0.35, 0.10], ["CC", "CG", "GG"], ["liver"], "脂肪肝遗传易感性"),
    ("CDKN2A/B (rs10811661)", "cdkn2a", [0.30, 0.50, 0.20], ["TT", "TC", "CC"], ["t2d"], "影响胰岛 β 细胞功能"),
]


# ── Microbiome (12 key taxa) ───────────────────────────────────
_MICRO_DEFS = [
    ("Akkermansia muciniphila", "akkermansia", 0.01, 0.04, ["cgm", "weight"], "肠道黏膜守护者，保护肠屏障，降低代谢病风险"),
    ("Faecalibacterium prausnitzii", "faecalibacterium", 0.05, 0.15, ["inflammation"], "主要产丁酸菌，抗炎保护"),
    ("Bifidobacterium", "bifidobacterium", 0.02, 0.10, ["cgm"], "改善糖耐量，常见于母乳喂养及健康肠道"),
    ("Lactobacillus", "lactobacillus", 0.005, 0.03, ["mood"], "乳酸菌，肠脑轴关键群体"),
    ("Roseburia", "roseburia", 0.02, 0.08, ["cgm"], "产丁酸，维持能量代谢"),
    ("Bacteroides", "bacteroides", 0.10, 0.30, ["diet"], "主要拟杆菌属，受饮食结构影响"),
    ("Prevotella", "prevotella", 0.02, 0.20, ["diet"], "高膳食纤维人群丰富"),
    ("Ruminococcus", "ruminococcus", 0.02, 0.10, ["diet"], "降解复杂多糖的核心菌"),
    ("Blautia", "blautia", 0.05, 0.15, ["weight"], "与体重/代谢健康相关"),
    ("Eubacterium rectale", "eubacterium", 0.03, 0.12, ["cgm"], "产丁酸菌，调节肠道稳态"),
    ("Clostridium difficile", "c_difficile", 0.0, 0.005, ["inflammation"], "低丰度为正常，高值提示菌群紊乱"),
    ("Enterobacteriaceae", "enterobacteriaceae", 0.001, 0.02, ["inflammation"], "低丰度为正常，过多提示肠道炎症"),
]


def _tri_value(rng: random.Random, lo: float, hi: float, skew: float = 0.0) -> float:
    """Triangular-ish draw biased by skew. skew>0 biases high."""
    base = rng.triangular(lo * 0.85, hi * 1.15, lo + (hi - lo) * (0.5 + skew * 0.3))
    return round(max(0.0, base), 3 if base < 10 else 1)


def build_metabolomics(user_id: int) -> dict:
    rng = random.Random(_seed_for(user_id) ^ 0xA11)
    # Give each user a mild "theme" (insulin-resistant leaning vs healthy leaning)
    skew = rng.uniform(-0.4, 0.6)
    items: list[DemoItem] = []
    for name, key, lo, hi, unit, rel, story in _METAB_DEFS:
        v = _tri_value(rng, lo, hi, skew=skew if "t2d" in rel or "cgm" in rel else skew * 0.3)
        status = _status(v, lo, hi)
        items.append(DemoItem(
            name=name, key=key, value=v, unit=unit, status=status,
            reference=f"{lo}–{hi} {unit}", story_zh=story, relevance=rel,
        ))
    summary_parts = [i for i in items if i.status in ("high", "low")]
    metabolic_age_delta = round(rng.uniform(-3.5, 6.5), 1)
    return {
        "is_demo": True,
        "metabolic_age_delta_years": metabolic_age_delta,
        "overall_risk": "中风险" if skew > 0.2 else ("低风险" if skew < -0.1 else "中风险"),
        "summary": _metab_summary(summary_parts, metabolic_age_delta),
        "items": [i.__dict__ for i in items],
    }


def _metab_summary(highlights: list[DemoItem], metabolic_age_delta: float) -> str:
    if not highlights:
        return f"代谢组整体处于健康区间，代谢年龄较实际年龄 {('+' if metabolic_age_delta >= 0 else '')}{metabolic_age_delta} 岁。"
    top = highlights[:3]
    names = "、".join(h.name.split(" ")[0] for h in top)
    direction = "偏高" if sum(1 for h in top if h.status == "high") >= len(top) / 2 else "偏离参考区间"
    return f"{names} {direction}，提示胰岛素敏感性与心血管代谢值得关注。代谢年龄 {('+' if metabolic_age_delta >= 0 else '')}{metabolic_age_delta} 岁。"


def build_proteomics(user_id: int) -> dict:
    rng = random.Random(_seed_for(user_id) ^ 0xB22)
    skew = rng.uniform(-0.3, 0.5)
    items: list[DemoItem] = []
    for name, key, lo, hi, unit, rel, story in _PROT_DEFS:
        v = _tri_value(rng, lo, hi, skew=skew if "inflammation" in rel else skew * 0.5)
        status = _status(v, lo, hi)
        items.append(DemoItem(
            name=name, key=key, value=v, unit=unit, status=status,
            reference=f"{lo}–{hi} {unit}", story_zh=story, relevance=rel,
        ))
    inflammation_score = round(min(100, max(0, 30 + skew * 50 + rng.uniform(-8, 8))), 0)
    return {
        "is_demo": True,
        "inflammation_score": inflammation_score,
        "summary": _prot_summary(items, inflammation_score),
        "items": [i.__dict__ for i in items],
    }


def _prot_summary(items: list[DemoItem], score: float) -> str:
    level = "低" if score < 35 else ("中" if score < 65 else "高")
    abnorm = [i for i in items if i.status in ("high", "low")]
    if abnorm:
        names = "、".join(i.name.split(" ")[0] for i in abnorm[:3])
        return f"慢性炎症综合评分 {int(score)}/100（{level}），{names} 偏离参考区间。"
    return f"慢性炎症综合评分 {int(score)}/100（{level}），主要蛋白标志物处于健康区间。"


def build_genomics(user_id: int) -> dict:
    rng = random.Random(_seed_for(user_id) ^ 0xC33)
    variants: list[dict] = []
    for name, key, probs, labels, rel, story in _GENE_DEFS:
        idx = _weighted_pick(rng, probs)
        geno = labels[idx]
        risk_level = "低" if idx == 0 else ("中" if idx <= len(labels) // 2 else "较高")
        variants.append({
            "name": name,
            "key": key,
            "genotype": geno,
            "risk_level": risk_level,
            "relevance": rel,
            "story_zh": story,
        })
    prs_t2d = round(rng.uniform(-0.8, 1.5), 2)
    prs_cvd = round(rng.uniform(-0.6, 1.3), 2)
    prs_masld = round(rng.uniform(-0.7, 1.4), 2)
    return {
        "is_demo": True,
        "prs": {
            "t2d": prs_t2d,
            "cvd": prs_cvd,
            "masld": prs_masld,
        },
        "summary": _gene_summary(prs_t2d, prs_cvd, prs_masld),
        "variants": variants,
    }


def _gene_summary(prs_t2d: float, prs_cvd: float, prs_masld: float) -> str:
    worst = max(("T2D", prs_t2d), ("CVD", prs_cvd), ("MASLD", prs_masld), key=lambda x: x[1])
    if worst[1] > 0.5:
        return f"多基因风险评分显示 {worst[0]} 倾向略高（PRS {worst[1]:+.2f}），通过生活方式可有效缓解遗传倾向。"
    return "多基因风险评分整体平衡，遗传倾向不构成显著风险因素。"


def _weighted_pick(rng: random.Random, probs: list[float]) -> int:
    r = rng.random()
    acc = 0.0
    for i, p in enumerate(probs):
        acc += p
        if r <= acc:
            return i
    return len(probs) - 1


def build_microbiome(user_id: int) -> dict:
    rng = random.Random(_seed_for(user_id) ^ 0xD44)
    # Sample raw values then normalise to relative abundance
    raw: list[tuple[str, str, float, float, list[str], str, float]] = []
    for name, key, lo, hi, rel, story in _MICRO_DEFS:
        v = rng.uniform(lo * 0.4, hi * 1.4)
        raw.append((name, key, lo, hi, rel, story, v))
    total = sum(r[-1] for r in raw)
    taxa: list[dict] = []
    for name, key, lo, hi, rel, story, v in raw:
        rel_ab = v / total
        status = _status(rel_ab, lo, hi)
        taxa.append({
            "name": name,
            "key": key,
            "relative_abundance": round(rel_ab, 4),
            "reference": f"{lo}–{hi}",
            "status": status,
            "relevance": rel,
            "story_zh": story,
        })
    shannon = round(-sum(t["relative_abundance"] * math.log(t["relative_abundance"] + 1e-9) for t in taxa), 2)
    scfa_score = round(sum(t["relative_abundance"] for t in taxa if any(r in ("cgm",) for r in t["relevance"])) * 100, 0)
    return {
        "is_demo": True,
        "shannon": shannon,
        "scfa_producer_pct": scfa_score,
        "summary": f"肠道多样性 Shannon={shannon}，SCFA 产生菌占比 {int(scfa_score)}%。",
        "taxa": taxa,
    }


# ── Cross-omics triad (metabolomics × CGM × heart rate) ────────

def build_triad(user_id: int) -> dict:
    """Fake but consistent cross-tab insight that animates well."""
    rng = random.Random(_seed_for(user_id) ^ 0xE55)
    # Each score in [0, 1]; higher = more abnormal signal
    metab = round(rng.uniform(0.25, 0.7), 2)
    cgm = round(rng.uniform(0.2, 0.75), 2)
    heart = round(rng.uniform(0.15, 0.6), 2)
    overlap = min(metab, cgm, heart)
    insights: list[str] = []
    if metab > 0.5 and cgm > 0.5:
        insights.append("BCAA 升高与餐后血糖峰值偏高同步，提示胰岛素敏感性下降早期信号。")
    if cgm > 0.5 and heart > 0.45:
        insights.append("血糖波动高峰时段静息心率偏高，自主神经受血糖波动影响明显。")
    if metab > 0.5 and heart > 0.45:
        insights.append("TMAO / 神经酰胺偏高与心率变异下降一致，心血管负担值得关注。")
    if not insights:
        insights.append("三维指标整体平衡，代谢-心脏-血糖系统处于健康耦合状态。")
    return {
        "is_demo": True,
        "metabolomics_score": metab,
        "cgm_score": cgm,
        "heart_score": heart,
        "overlap_score": overlap,
        "insights": insights,
    }
