from __future__ import annotations

import re


_TRIAGE_BOUNDARIES: tuple[tuple[set[str], re.Pattern[str], str], ...] = (
    (
        {"headache"},
        re.compile(r"突然.{0,8}(?:最严重|剧烈)|发热.{0,8}颈|颈.{0,8}僵|反复呕吐|视物异常|说话不清|一侧无力|半边无力"),
        "若头痛突然达到最严重程度，或伴发热颈部僵硬、反复呕吐、视物或说话异常、一侧无力，立即就医。",
    ),
    (
        {"dizziness"},
        re.compile(r"晕倒|昏厥|胸痛|呼吸困难|说话不清|一侧无力|持续站立不稳"),
        "若头晕伴昏厥、胸痛、呼吸困难、说话不清、一侧无力或持续无法站稳，立即就医。",
    ),
    (
        {"abdominal_pain", "stomach_pain"},
        re.compile(r"突然剧烈|腹部僵硬|黑便|便血|呕血|持续呕吐|孕期|怀孕"),
        "若腹痛突然剧烈、腹部僵硬，或伴黑便、便血、呕血、持续呕吐，孕期出现明显腹痛时，立即就医。",
    ),
    (
        {"diarrhea", "nausea_vomiting"},
        re.compile(r"无法进水|喝不下|明显脱水|尿量明显减少|便血|黑便|呕血|持续高热"),
        "若持续无法进水、尿量明显减少，或出现便血、黑便、呕血、持续高热，尽快就医。",
    ),
    (
        {"rash", "allergy"},
        re.compile(r"面部肿|舌.{0,4}肿|喉咙.{0,4}紧|呼吸困难|喘不上气|意识异常"),
        "若皮疹或过敏伴面部、舌头肿胀，喉咙发紧、呼吸困难或意识异常，立即拨打 120。",
    ),
    (
        {"cough", "sore_throat"},
        re.compile(r"呼吸困难|喘不上气|口唇发紫|无法吞咽|流口水|意识异常"),
        "若咳嗽或咽痛伴呼吸困难、口唇发紫、无法吞咽、持续流口水或意识异常，立即就医。",
    ),
    (
        {"fever"},
        re.compile(r"意识模糊|颈部僵硬|抽搐|呼吸困难|紫癜|按压不褪色"),
        "若发热伴意识模糊、颈部僵硬、抽搐、呼吸困难，或出现按压不褪色的紫红皮疹，立即就医。",
    ),
    (
        {"edema"},
        re.compile(r"单侧腿肿|一条腿肿|胸痛|呼吸困难|突然气短"),
        "若水肿突然只出现在一侧腿部，或同时出现胸痛、呼吸困难、突然气短，立即就医。",
    ),
    (
        {"palpitations"},
        re.compile(r"胸痛|呼吸困难|昏厥|晕倒|持续.{0,8}不缓解"),
        "若心悸伴胸痛、呼吸困难、昏厥，或持续不缓解，立即就医。",
    ),
)


def missing_symptom_boundary(concept_keys: list[str], visible_text: str) -> str | None:
    keys = set(concept_keys or [])
    for relevant, marker, boundary in _TRIAGE_BOUNDARIES:
        if keys.intersection(relevant):
            return None if marker.search(visible_text or "") else boundary
    return None
