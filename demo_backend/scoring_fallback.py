"""When the scoring API fails, score only what the student actually said."""

from __future__ import annotations

import re
from typing import Any


DIMENSIONS = [
    ("病史采集完整性", 30),
    ("共情与情绪回应", 20),
    ("健康教育准确性", 20),
    ("沟通技巧与语言通俗性", 15),
    ("职业素养与人文关怀", 15),
]


def fallback_lin_hao_report(transcript: list[dict[str, Any]]) -> dict[str, Any]:
    students = [item for item in transcript if item.get("role") == "student"]

    def first(pattern: str) -> dict[str, Any] | None:
        return next((item for item in students if re.search(pattern, item["text"])), None)

    def evidence(item: dict[str, Any] | None, missing: str) -> str:
        if item is None:
            return f"本场未涉及{missing}。"
        text = item["text"][:28]
        return f"第{item['turn']}轮说“{text}{'…' if len(item['text']) > 28 else ''}”"

    history_items = [
        ("疼痛部位和程度", r"哪里疼|哪儿疼|疼痛|几分|程度"),
        ("疼痛诱因", r"翻身|咳嗽|活动|什么时候更疼"),
        ("伴随不适", r"恶心|呕吐|发热|发烧|体温"),
        ("伤口情况", r"伤口|切口|渗血|红肿"),
        ("活动情况", r"下床|走动|活动"),
        ("家庭支持", r"家人|家属|陪护|一个人"),
    ]
    covered = [name for name, pattern in history_items if first(pattern)]
    history_hit = next((first(pattern) for _, pattern in history_items if first(pattern)), None)
    history_score = min(29, 5 + 4 * len(covered)) if students else 0
    history_comment = (
        f"{evidence(history_hit, '术后病史采集')}，已涉及{'、'.join(covered)}；仍可补问未覆盖项目。"
        if history_hit else "本场未涉及疼痛、伴随不适或活动情况等术后病史采集。"
    )

    empathy_hit = first(r"理解|担心|害怕|紧张|别着急|放心|慢慢|陪您|辛苦")
    empathy_score = (8 + (10 if empathy_hit else 0)) if students else 0
    empathy_comment = (
        f"{evidence(empathy_hit, '情绪回应')}，回应了林先生对疼痛和伤口的担忧。"
        if empathy_hit else "本场未涉及对林先生疼痛焦虑的直接回应。"
    )

    education_items = [
        ("疼痛报告", r"及时告诉|疼痛.{0,8}说|痛了.{0,8}说"),
        ("安全活动", r"翻身|下床|活动|循序渐进|陪同"),
        ("伤口观察", r"伤口|切口|渗血|红肿|观察"),
        ("呼吸咳嗽", r"深呼吸|咳嗽|保护切口"),
    ]
    taught = [name for name, pattern in education_items if first(pattern)]
    education_hit = next((first(pattern) for _, pattern in education_items if first(pattern)), None)
    education_score = min(19, 4 + 4 * len(taught)) if students and taught else (4 if students else 0)
    education_comment = (
        f"{evidence(education_hit, '术后健康教育')}，已涉及{'、'.join(taught)}；可请患者复述安全做法。"
        if education_hit else "本场未涉及疼痛报告、安全活动或伤口观察等具体健康教育。"
    )

    open_hit = first(r"什么|怎么|哪里|哪儿|感受|顾虑|担心|方便.{0,4}说")
    communication_score = (7 + (7 if open_hit else 0)) if students else 0
    communication_comment = (
        f"{evidence(open_hit, '开放式提问')}，提问清楚并给患者表达空间。"
        if open_hit else "本场未涉及充分的开放式提问或通俗解释。"
    )

    greeting_hit = first(r"您好|你好|我是.{0,8}护士|林先生")
    privacy_hit = first(r"隐私|方便|家属|陪护")
    professionalism_score = (6 + (5 if greeting_hit else 0) + (3 if privacy_hit else 0)) if students else 0
    professionalism_comment = (
        f"{evidence(greeting_hit, '得体称呼和身份介绍')}，称呼与身份交代得体。"
        if greeting_hit else "本场未涉及得体称呼或护士身份介绍。"
    )

    dimensions = [
        {"name": DIMENSIONS[0][0], "weight": DIMENSIONS[0][1], "score": history_score, "comment": history_comment},
        {"name": DIMENSIONS[1][0], "weight": DIMENSIONS[1][1], "score": empathy_score, "comment": empathy_comment},
        {"name": DIMENSIONS[2][0], "weight": DIMENSIONS[2][1], "score": education_score, "comment": education_comment},
        {"name": DIMENSIONS[3][0], "weight": DIMENSIONS[3][1], "score": communication_score, "comment": communication_comment},
        {"name": DIMENSIONS[4][0], "weight": DIMENSIONS[4][1], "score": professionalism_score, "comment": professionalism_comment},
    ]
    suggestions = []
    if len(students) < 4:
        suggestions.append("对话轮次不足，评分仅供参考；建议至少完成4轮沟通。")
    if not empathy_hit:
        suggestions.append("先复述林先生担心伤口裂开的顾虑，再说明会陪同评估。")
    if len(covered) < 4:
        missing = [name for name, _ in history_items if name not in covered]
        suggestions.append(f"病史采集可补充{'、'.join(missing[:2])}，每次聚焦一个问题。")
    if len(taught) < 3:
        missing = [name for name, _ in education_items if name not in taught]
        suggestions.append(f"健康教育可补充{'、'.join(missing[:2])}，并请患者复述。")
    suggestions.extend([
        "结束前确认林先生是否仍担心活动会使伤口裂开。",
        "说明活动建议时使用短句，并先确认医嘱和患者当前状态。",
    ])
    return {"total_score": sum(x["score"] for x in dimensions), "dimensions": dimensions, "suggestions": suggestions[:3]}


def fallback_report(transcript: list[dict[str, Any]], case_id: str = "wang_ayi") -> dict[str, Any]:
    if case_id == "human_candidate":
        return fallback_lin_hao_report(transcript)
    students = [item for item in transcript if item.get("role") == "student"]

    def first(pattern: str) -> dict[str, Any] | None:
        return next((item for item in students if re.search(pattern, item["text"])), None)

    def quote(item: dict[str, Any]) -> str:
        value = item["text"][:32]
        return f"第{item['turn']}轮说“{value}{'…' if len(item['text']) > 32 else ''}”"

    def dimension(name: str, weight: int, score: int, comment: str) -> dict[str, Any]:
        return {"name": name, "weight": weight, "score": max(0, min(weight, score)), "comment": comment}

    history = [
        ("主诉", r"哪里不舒服|哪儿不舒服|哪里难受|什么症状|感觉哪里"),
        ("病程", r"什么时候|多久|多长时间|一直|加重|变化"),
        ("用药", r"吃药|用药|服药|药物|二甲双胍|胰岛素"),
        ("既往史", r"既往史|其他病|以前.{0,5}病|得过什么病"),
        ("家庭支持", r"家人|家属|孩子|儿女|独居|一个人住"),
        ("生活与经济", r"花费|费用|退休金|经济|生活习惯|平时.{0,5}吃"),
    ]
    covered = [name for name, pattern in history if first(pattern)]
    missing = [name for name, _ in history if name not in covered]
    history_hit = next((first(pattern) for _, pattern in history if first(pattern)), None)
    history_score = min(29, 5 + 4 * len(covered)) if students else 0
    history_comment = (
        f"{quote(history_hit)}，本场涉及{'、'.join(covered)}；" +
        (f"尚未询问{'、'.join(missing)}。" if missing else "病史覆盖较完整，可继续核实细节。")
        if history_hit else f"{quote(students[0])}，本场未涉及主诉、病程、用药等病史采集。" if students else "本场对话未涉及病史采集。"
    )

    empathy_hit = first(r"我理解|理解您|听出.{0,8}担心|您.{0,5}担心|最害怕|最怕|辛苦|陪您|慢慢说|别着急")
    support_hit = first(r"我理解|理解您|听您说|陪您|慢慢说|一起想|辛苦")
    cancer_hit = first(r"癌症|肿瘤|绝症")
    weather_hit = first(r"天气|新闻|明星|球赛")
    empathy_score = (4 + (7 if empathy_hit else 0) + (5 if support_hit else 0) - (2 if cancer_hit else 0) - (2 if weather_hit else 0)) if students else 0
    empathy_comment = (
        f"{quote(empathy_hit)}，回应了患者情绪；" +
        (f"但{quote(cancer_hit)}可能加重焦虑。" if cancer_hit else "可继续倾听患者的担心。")
        if empathy_hit else f"{quote(students[0])}，本场未涉及对患者焦虑的直接回应或安抚。" if students else "本场对话未涉及情绪回应。"
    )

    education = [
        ("饮食", r"饮食|主食|少糖|饭菜|吃饭|饮食调整"),
        ("足部护理", r"洗脚|擦干|足底|脚底|破损|破皮|伤口|足部护理"),
        ("活动", r"散步|活动|运动"),
        ("血糖监测", r"测血糖|血糖监测|监测血糖|血糖数值"),
    ]
    taught = [name for name, pattern in education if first(pattern)]
    education_hit = next((first(pattern) for _, pattern in education if first(pattern)), None)
    actual_advice = first(r"注意擦干|检查有无|每天检查|洗后擦干|饮食调整|少吃|少糖|及时告诉|可以.{0,10}护理|规律.{0,5}(?:吃饭|运动|活动|监测)|避免赤脚")
    education_score = (min(19, 3 * len(taught) + 5) if actual_advice else min(8, 2 * len(taught))) if students else 0
    education_comment = (
        (f"{quote(actual_advice)}，涉及{'、'.join(taught)}；" +
         (f"尚可补充{'、'.join(name for name, _ in education if name not in taught)}。" if len(taught) < 4 else "可请患者复述理解的做法。"))
        if actual_advice else
        (f"{quote(education_hit)}只询问了相关情况，未涉及具体健康教育。" if education_hit else f"{quote(students[0])}，本场未涉及饮食、足部护理、活动或血糖监测教育。" if students else "本场对话未涉及健康教育。")
    )

    open_questions = [item for item in students if re.search(r"什么|怎么|哪里|哪件|感受|顾虑|说说|方便吗", item["text"])]
    open_hit = open_questions[0] if open_questions else None
    communication_score = (6 + min(8, len(open_questions) * 2) - (4 if cancer_hit else 0) - (3 if weather_hit else 0)) if students else 0
    communication_comment = (
        f"{quote(open_hit)}，使用了容易理解的提问；" +
        (f"但{quote(weather_hit)}偏离病情。" if weather_hit else "可继续多用开放式追问。")
        if open_hit else f"{quote(students[0])}，本场未涉及充分的开放式提问。" if students else "本场对话未涉及开放式提问。"
    )

    greeting_hit = first(r"阿姨您好|阿姨好|我是.{0,8}护士|王阿姨")
    patience_hit = first(r"谢谢|慢慢|陪您|理解您|我理解")
    privacy_hit = first(r"隐私|方便.{0,8}说|家人|家属")
    professionalism_score = (5 + (4 if greeting_hit else 0) + (3 if patience_hit else 0) + (2 if privacy_hit else 0) - (3 if cancer_hit else 0) - (2 if weather_hit else 0)) if students else 0
    professionalism_comment = (
        f"{quote(greeting_hit)}，称呼和身份交代得体；" +
        (f"但{quote(cancer_hit)}不利于保护患者情绪。" if cancer_hit else "可继续保持耐心并说明隐私保护。")
        if greeting_hit else f"{quote(students[0])}，本场未涉及得体称呼或身份介绍。" if students else "本场对话未涉及得体称呼或身份介绍。"
    )

    dimensions = [
        dimension(*DIMENSIONS[0], history_score, history_comment),
        dimension(*DIMENSIONS[1], empathy_score, empathy_comment),
        dimension(*DIMENSIONS[2], education_score, education_comment),
        dimension(*DIMENSIONS[3], communication_score, communication_comment),
        dimension(*DIMENSIONS[4], professionalism_score, professionalism_comment),
    ]

    suggestions = []
    if len(students) < 4:
        suggestions.append("对话轮次不足，评分仅供参考；建议至少完成4轮沟通。")
    if cancer_hit:
        suggestions.append(f"第{cancer_hit['turn']}轮直接提癌症易加重焦虑；可先问患者担心的并发症，并由医生解释诊断。")
    if weather_hit:
        suggestions.append(f"第{weather_hit['turn']}轮转向天气偏离主诉；可追问脚麻对睡眠和日常活动的影响。")
    if missing:
        suggestions.append(f"病史采集尚缺{'、'.join(missing[:2])}；下次可在主诉后逐项补问。")
    if not empathy_hit:
        suggestions.append("先复述王阿姨的担心，再问她最害怕出现什么情况。")
    if education_hit and not actual_advice:
        suggestions.append(f"第{education_hit['turn']}轮询问相关习惯后，可说明一项具体做法，并请王阿姨复述。")
    elif len(taught) < 4:
        suggestions.append(f"健康教育可补充{'、'.join(name for name, _ in education if name not in taught)[:2]}，并请患者复述做法。")
    suggestions.extend([
        "在足部护理说明后，请王阿姨用自己的话复述洗脚和检查步骤。",
        "结束前问王阿姨还有什么担忧，再确认她理解了今天的护理建议。",
        "每次提问只聚焦一个问题，给王阿姨留出完整回答的时间。",
    ])
    return {
        "total_score": sum(item["score"] for item in dimensions),
        "dimensions": dimensions,
        "suggestions": suggestions[:3],
    }
