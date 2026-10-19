"""病例内的预设应答：模型拥堵时维持患者身份和演示边界。"""

from __future__ import annotations

import re


RESPONSES = {
    "opening": ("哎，我这糖尿病十几年了，最近脚发麻，眼睛也看不清，心里慌得很。", "焦虑"),
    "cancer": ("哎，医生说我是糖尿病。我就是怕并发症，听说脚不好会截肢。", "焦虑"),
    "weather": ("哎，我哪有心思管那个。护士啊，我这脚麻到底要紧不？", "焦虑"),
    "duration": ("哎，脚麻有一个月了，两只脚都发凉。最近看东西也模糊。", "焦虑"),
    "duration_medication": ("哎，脚麻有一个月了。药是二甲双胍和胰岛素，可血糖还是不太稳。", "焦虑"),
    "medication": ("哎，平时吃二甲双胍，也打胰岛素。可血糖一直不太稳。", "焦虑"),
    "treatment": ("哎，这我哪懂啊，就听医生的呗。我只怕这脚麻越来越重。", "焦虑"),
    "fear": ("唉，我最怕脚出了问题，还怕看不清东西。孩子们不在身边，我心里慌。", "焦虑"),
    "empathy": ("哎，您这么耐心听我说，我心里踏实些。就是还担心这脚麻。", "感激"),
    "diet": ("哎，吃饭和测血糖该怎么安排，您慢慢跟我说。我一个人住，也想学着照顾好自己。", "平静"),
    "foot": ("哎，我这双脚发麻，眼睛也看不清。您说洗后擦干、看看脚有没有破皮，我记下了。", "平静"),
    "wound": ("哎，要是真有伤口，我会马上告诉您。您可得教教我怎么仔细看脚。", "平静"),
    "activity": ("哎，我这脚麻着，活动的事我有点怕。您慢慢说，我听着。", "焦虑"),
    "glucose": ("唉，医生说我血糖控制得不太理想。监测血糖的事，您慢慢跟我讲，我记着。", "焦虑"),
    "lab_values": ("唉，具体血糖数值我记不清了。医生说控制得不太稳，我心里发慌。", "焦虑"),
    "family": ("哎，老伴走了三年了，儿女都在外地，平时就我一个人住。", "平静"),
    "cost": ("唉，住院花钱，我退休金就三千多，还怕拖累儿女。", "焦虑"),
    "history": ("我知道自己有糖尿病十二年了。别的病我不敢乱说，您可以看看病历。", "平静"),
    "generic": ("哎……你刚才说啥，我没听清。", "焦虑"),
}


# Reviewed Wang Ayi lines.  The model may select an ID but may never rewrite
# the sentence, so the displayed text, cached cloned voice and lip driver stay
# identical while every answer remains inside the documented case boundary.
WANG_AYI_RESPONSE_BANK = {
    "opening": ("哎，我这两只脚发麻发凉，看东西也有点模糊，心里一直不踏实。", "焦虑", "opening"),
    "opening_2": ("护士啊，我最近最难受的是脚麻，眼睛看不清，也不知道是不是严重了。", "焦虑", "opening"),
    "foot_numbness": ("两只脚都麻，像隔着一层东西似的，已经有一个月了。", "焦虑", "symptom"),
    "foot_cold": ("两只脚总觉得发凉，跟脚麻一起出现的，我心里挺害怕。", "焦虑", "symptom"),
    "vision": ("最近看东西有点模糊，具体是什么原因我不知道，得请医生检查。", "焦虑", "vision"),
    "duration": ("脚麻脚凉差不多一个月了，最近看东西也有点模糊。", "平静", "duration"),
    "duration_2": ("大概是这个月开始明显的，具体哪一天我记不清了。", "平静", "duration"),
    "diabetes_history": ("我得二型糖尿病十二年了，这次就是脚麻和看不清让我害怕。", "平静", "history"),
    "diagnosis": ("医生说我是二型糖尿病，别的诊断我可不敢自己乱说。", "平静", "diagnosis"),
    "medication": ("平时吃二甲双胍，也打胰岛素。具体剂量您还是看病历吧。", "平静", "medication"),
    "medication_2": ("药就是二甲双胍和胰岛素，怎么调整得听医生的，我不敢自己做主。", "平静", "medication"),
    "adherence_unknown": ("我用药的具体记录一时说不全，您可以帮我核对病历，别按我猜的来。", "平静", "medication_unknown"),
    "lab_unknown": ("具体血糖数值我记不清了，只知道医生说控制得不太理想。", "焦虑", "lab"),
    "glucose_control": ("医生说血糖控制得不太理想，我也担心脚麻跟这个有关系。", "焦虑", "glucose"),
    "complication_fear": ("我就是怕糖尿病出了并发症，又不敢往坏处想，心里慌得很。", "焦虑", "fear"),
    "amputation_fear": ("我听邻居说糖尿病严重了会截肢，我最怕自己的脚也变成那样。", "焦虑", "fear"),
    "blindness_fear": ("最近看东西模糊，我就怕以后会看不见。您说我能不慌吗？", "焦虑", "fear"),
    "fear_general": ("我最怕脚越来越麻、眼睛越来越看不清，还怕拖累孩子。", "焦虑", "fear"),
    "empathy": ("哎，您愿意耐心听我说，我心里总算踏实一点了。", "感激", "empathy"),
    "empathy_2": ("谢谢您没嫌我唠叨。您慢慢讲，我也愿意好好配合。", "感激", "empathy"),
    "dismissive": ("可我脚麻、眼睛也模糊，光说没事我还是不放心。您能帮我仔细看看吗？", "焦虑", "dismissal"),
    "dismissive_2": ("我不是故意多想，是真的害怕并发症。您听我把担心说完行吗？", "抗拒", "dismissal"),
    "family": ("儿子女儿都在外地工作，平时只能打电话问问我。", "平静", "family"),
    "family_2": ("孩子们都不在身边，这次还是女儿打电话发现不对，才送我来住院的。", "焦虑", "family"),
    "widow": ("老伴三年前走了，家里平时就我一个人，遇到生病心里更没底。", "焦虑", "family"),
    "living_alone": ("我平时一个人住，儿女都在外地，所以也担心没人照应。", "焦虑", "family"),
    "cost": ("我退休金一个月三千多，住院花钱多了，我怕给孩子添负担。", "焦虑", "cost"),
    "cost_2": ("钱的事我确实担心，可病也不能不看。您能告诉我该找谁咨询费用吗？", "平静", "cost"),
    "occupation": ("我退休前是小学语文老师，现在已经退休了。", "平静", "identity"),
    "identity": ("我叫王秀兰，今年六十八岁，大家都叫我王阿姨。", "平静", "identity"),
    "diet_unknown": ("我平时具体怎么吃，一下子说不全面。您可以一项一项问我。", "平静", "diet"),
    "diet_education": ("好，您用简单的话告诉我怎么安排吃饭，我会认真记。", "平静", "education"),
    "monitoring_unknown": ("平时监测的具体次数和记录我说不准，您可以帮我看看病历。", "平静", "monitoring"),
    "foot_care": ("您说每天看看脚、洗完擦干，我记住了。还有什么要特别注意的吗？", "平静", "foot_care"),
    "foot_check": ("我眼睛有点模糊，自己看脚不太方便。您能教我怎么检查吗？", "焦虑", "foot_care"),
    "wound_unknown": ("脚上有没有细小破损我自己看不清，不敢乱说，得麻烦您检查。", "焦虑", "wound"),
    "exercise_concern": ("我脚麻着，活动时有点怕。您先告诉我怎么做才安全吧。", "焦虑", "activity"),
    "exercise_accept": ("好，只要您说明白怎么安全活动，我愿意慢慢配合。", "平静", "education"),
    "treatment": ("怎么治疗我不懂，得听医生安排。我想先知道这脚麻要注意什么。", "平静", "treatment"),
    "nurse_role": ("我知道您不能替医生下诊断。您先帮我把情况问清楚，再请医生判断吧。", "平静", "role"),
    "allergy_unknown": ("过敏这些具体情况我记不准，麻烦您核对病历，别让我乱猜。", "平静", "unknown"),
    "other_history": ("我知道自己有糖尿病十二年了，别的病我不敢乱说，您看看病历吧。", "平静", "history"),
    "vital_unknown": ("血压、体温这些具体数值我不知道，还是要按实际测量结果看。", "平静", "unknown"),
    "jargon": ("哎，您说的这些词我听不太懂，能不能换成简单一点的话？", "抗拒", "jargon"),
    "hostile": ("你这么催我，我心里更慌了。能不能慢一点，先听我把话说完？", "抗拒", "pressure"),
    "irrelevant": ("哎，我现在哪有心思聊这个。我就想知道脚麻到底要不要紧。", "焦虑", "irrelevant"),
    "clarify": ("我没太明白您想问哪一点，是脚麻、眼睛，还是用药的事？", "平静", "clarify"),
    "closing": ("好，谢谢您。我会按您说的注意，有不清楚的再问您。", "感激", "closing"),
    "repeat": ("我主要就是两只脚麻凉、看东西模糊，也担心糖尿病并发症。", "平静", "clarify"),
    "cooperation": ("您慢慢问吧，我知道的都会告诉您，不清楚的咱们就查病历。", "平静", "opening"),
}


def wang_ayi_response(response_id: str) -> tuple[str, str, str]:
    try:
        return WANG_AYI_RESPONSE_BANK[response_id]
    except KeyError:
        raise ValueError(f"unknown Wang Ayi response id: {response_id}") from None


def wang_ayi_response_catalog(recent_ids: list[str] | tuple[str, ...] = ()) -> str:
    recent = set(recent_ids[-4:])
    return "\n".join(
        f"- {response_id} | {intent} | {emotion} | {text}"
        + ("（最近已用，优先换一句）" if response_id in recent else "")
        for response_id, (text, emotion, intent) in WANG_AYI_RESPONSE_BANK.items()
    )


def select_wang_ayi_response(
    question: str,
    recent_ids: list[str] | tuple[str, ...] = (),
) -> tuple[str, str, str, str]:
    q = re.sub(r"\s+", "", question)
    if re.search(r"谢谢|辛苦了|先这样|明白了|知道了|结束|再见", q): intent = "closing"
    elif re.search(r"天气|下雨|晴天|新闻|明星|电影|球赛|股票|游戏", q): intent = "irrelevant"
    elif re.search(r"我理解|理解您|别着急|我陪|听您说|辛苦|慢慢说", q): intent = "empathy"
    elif re.search(r"没事|想太多|别担心|矫情|大惊小怪|忍一忍", q): intent = "dismissal"
    elif re.search(r"必须|赶紧|快点|别磨蹭|啰嗦|唠叨", q): intent = "pressure"
    elif re.search(r"听不懂|专业术语|什么意思|明白吗", q): intent = "jargon"
    elif re.search(r"名字|叫什么|几岁|年龄|多大|老师|职业|退休", q): intent = "identity"
    elif re.search(r"老伴|儿子|女儿|孩子|家人|家属|独居|一个人住", q): intent = "family"
    elif re.search(r"费用|花钱|退休金|负担|经济", q): intent = "cost"
    elif re.search(r"过敏", q): intent = "unknown"
    elif re.search(r"血压|体温|心率|血氧|生命体征", q): intent = "unknown"
    elif re.search(r"既往史|以前有什么病|还有什么病|病史", q): intent = "history"
    elif re.search(r"血糖.{0,4}(多少|数值|高不高)|具体血糖|空腹血糖|糖化|化验", q): intent = "lab"
    elif re.search(r"什么药|吃药|用药|胰岛素|二甲双胍|药量", q): intent = "medication"
    elif re.search(r"什么时候|多久|多长时间|何时开始", q): intent = "duration"
    elif re.search(r"眼睛|视力|看不清|模糊|失明|瞎", q): intent = "vision" if not re.search(r"怕|担心|会不会", q) else "fear"
    elif re.search(r"截肢|并发症|最怕|害怕|担心|心慌|焦虑", q): intent = "fear"
    elif re.search(r"伤口|破皮|红肿|足底|脚底|检查脚", q): intent = "wound"
    elif re.search(r"洗脚|擦干|鞋袜|足部护理|怎么护理", q): intent = "foot_care"
    elif re.search(r"运动|散步|走动|活动", q): intent = "activity"
    elif re.search(r"饮食|吃饭|主食|甜食|怎么吃|吃什么", q): intent = "diet"
    elif re.search(r"测血糖|监测|记录血糖", q): intent = "monitoring"
    elif re.search(r"我不是医生|我不是大夫|不能诊断|护士能不能", q): intent = "role"
    elif re.search(r"怎么治|治疗|医生|护士|大夫", q): intent = "treatment"
    elif re.search(r"癌|肿瘤|糖尿病|得了什么病|什么病|诊断", q): intent = "diagnosis"
    elif re.search(r"脚麻|脚凉|发麻|发凉|哪里不舒服|怎么了|难受", q): intent = "symptom"
    else: intent = "clarify"
    candidates = [key for key, value in WANG_AYI_RESPONSE_BANK.items() if value[2] == intent]
    if not candidates:
        candidates = ["clarify"]
    recent = set(recent_ids[-4:])
    response_id = next((key for key in candidates if key not in recent), candidates[0])
    text, emotion, _ = wang_ayi_response(response_id)
    return response_id, text, emotion, intent

LIN_HAO_RESPONSE_BANK = {
    # Existing primary lines keep their IDs so the deployed audio remains valid.
    "opening": ("就是肚子这几个小切口还疼，翻身、咳嗽时更明显。我怕一动伤口就裂了。", "焦虑", "opening"),
    "pain": ("躺着是隐隐地疼，一翻身或者咳嗽就更疼。我现在有点不敢动。", "焦虑", "pain"),
    "duration": ("手术以后一直有点疼，今天翻身时感觉更明显。具体情况还得麻烦您帮我看看。", "焦虑", "duration"),
    "activity": ("我就是怕下床会把伤口扯开，所以一直不敢动。您能告诉我怎么做更安全吗？", "焦虑", "activity"),
    "wound": ("我不敢自己判断伤口怎么样，也没仔细碰过。能麻烦您帮我评估一下吗？", "焦虑", "wound"),
    "nausea": ("现在没有恶心，也没有吐。就是切口疼，心里有点紧张。", "平静", "nausea"),
    "fever": ("我自己没觉得发热，具体体温我不清楚。麻烦您按病历和测量结果判断。", "平静", "fever"),
    "fear": ("我最怕一活动伤口会裂，疼得更厉害。这是我第一次住院，心里没底。", "焦虑", "fear"),
    "empathy": ("谢谢您先听我说。您这么解释，我心里踏实一点了。", "感激", "empathy"),
    "family": ("家里人在外地，只能打电话问我。第一次住院，我一个人确实有点紧张。", "焦虑", "family"),
    "treatment": ("这个我不清楚，得听医生护士安排。我主要想知道怎么动才不会影响伤口。", "平静", "treatment"),
    "weather": ("这个我现在顾不上。我就担心一动伤口会裂，您能跟我说说吗？", "焦虑", "irrelevant"),
    "generic": ("嗯，您能说得再具体一点吗？我现在主要担心伤口和活动的问题。", "平静", "generic"),

    # Additional reviewed variants make the patient responsive without allowing
    # the model to invent a sentence that has no matching cloned-voice audio.
    "opening_2": ("现在最难受的还是切口疼，尤其翻身和咳嗽的时候。我有点怕碰到伤口。", "焦虑", "opening"),
    "pain_location": ("就是肚子上那几个小切口附近疼，别的地方我没觉得不舒服。", "平静", "pain"),
    "pain_scale": ("具体几分我不太会说。躺着还能忍，一翻身或咳嗽就明显疼起来。", "焦虑", "pain"),
    "pain_rest": ("安静躺着时是隐隐地疼，不动会轻一些，可我也不敢一直这样躺着。", "平静", "pain"),
    "pain_change": ("我说不好是不是更严重了，只觉得今天翻身时疼得明显。您能帮我评估一下吗？", "焦虑", "pain"),
    "duration_2": ("从手术后就有点疼，今天是术后第一天。翻身时比静静躺着更明显。", "平静", "duration"),
    "activity_how": ("如果您能告诉我先怎么翻身、怎么坐起来，我愿意慢慢试，就是怕扯到伤口。", "焦虑", "activity"),
    "activity_agree": ("好，您在旁边指导我的话，我可以慢一点试试。要是疼得厉害我会马上告诉您。", "平静", "activity_support"),
    "activity_decline": ("我现在确实害怕，直接让我下床我不太敢。能不能先告诉我怎么做，再陪我试？", "抗拒", "pressure"),
    "reassurance_doubt": ("可我一翻身或咳嗽就会疼，光休息真的可以吗？我还是担心伤口。", "焦虑", "dismissal"),
    "reassurance_doubt_2": ("休息时会轻一点，可一动还是疼。您这么说我还是不太放心，能帮我评估一下吗？", "焦虑", "dismissal"),
    "wound_assess": ("我没仔细看，也不敢说伤口有没有问题。麻烦您帮我看看，别让我自己猜。", "焦虑", "wound"),
    "wound_signs_unknown": ("有没有红肿、渗血我自己判断不了，得请您检查后再告诉我。", "平静", "wound"),
    "nausea_2": ("恶心和呕吐都没有。我现在主要是切口疼，还有点不敢活动。", "平静", "nausea"),
    "fever_2": ("我没有觉得发冷或发热，不过具体多少度我不知道，还是要麻烦您测一下。", "平静", "fever"),
    "fear_2": ("我第一次住院，很多事情都不懂。最担心的是一动就把伤口弄坏。", "焦虑", "fear"),
    "empathy_2": ("嗯，您愿意听我把担心说完，我就没那么慌了。谢谢您。", "感激", "empathy"),
    "family_2": ("家人不在身边，只能打电话联系。我一个人在医院，心里难免有点紧张。", "焦虑", "family"),
    "treatment_2": ("治疗怎么安排我不清楚，还是听医生护士的。我想先知道现在该怎么安全活动。", "平静", "treatment"),
    "medication_unknown": ("具体用了什么药、药量多少我说不准，您可以看病历或问医生。", "平静", "medication"),
    "diagnosis": ("医生说是急性阑尾炎，已经做了腹腔镜手术。现在是术后第一天。", "平静", "diagnosis"),
    "identity": ("我叫林浩，今年二十四岁。您叫我林先生就行。", "平静", "identity"),
    "work": ("我平时在公司上班。这次是第一次住院，所以心里有点没底。", "平静", "work"),
    "hospital_history": ("这是我第一次住院，以前没经历过这些，所以一疼我就容易紧张。", "焦虑", "history"),
    "allergy_unknown": ("过敏这些具体情况我说不准，麻烦您核对一下病历，别按我猜的来。", "平静", "allergy"),
    "vital_unknown": ("具体数值我不知道，也不敢乱说。麻烦您按实际测量和病历判断。", "平静", "vital"),
    "education_ack": ("好，我记住了，先慢一点，有不舒服就告诉您。您在旁边的话我会放心些。", "感激", "activity_support"),
    "role_clarify": ("我知道您不是替医生下诊断。我就是有点害怕，想请您先帮我看看、告诉我该怎么配合。", "平静", "role_clarify"),
    "role_clarify_2": ("您不是医生也没关系，我想先把不舒服说清楚。您能帮我记录，再请医生护士一起判断吗？", "平静", "role_clarify"),
    "jargon_confused": ("这个说法我没太听懂。您能不能用简单一点的话告诉我该注意什么？", "抗拒", "jargon"),
    "jargon_confused_2": ("这些词我听着有点糊涂。您直接告诉我现在该怎么配合就行。", "抗拒", "jargon"),
    "hostile": ("您这么说我更不敢动了。我现在确实会疼，能不能先听我说完？", "抗拒", "pressure"),
    "hostile_2": ("我不是故意不配合，是真的担心会疼、会碰到伤口。您先跟我说明白好吗？", "抗拒", "pressure"),
    "repeat_question": ("我主要是翻身和咳嗽时疼，也怕活动会影响伤口。您想先了解哪一方面？", "平静", "clarify"),
    "irrelevant_2": ("这个我现在没心思聊。我更想知道这疼痛和活动该怎么办。", "焦虑", "irrelevant"),
    "generic_2": ("我不太明白您想问哪一点。是想了解疼痛、伤口，还是活动时的感觉？", "平静", "generic"),
    "close_thanks": ("好，谢谢您。我会按您说的慢慢来，有不舒服就及时告诉您。", "感激", "closing"),
}

# Compatibility for the original quality probes and generation tooling.
LIN_HAO_RESPONSES = {
    response_id: (LIN_HAO_RESPONSE_BANK[response_id][0], LIN_HAO_RESPONSE_BANK[response_id][1])
    for response_id in (
        "opening", "pain", "duration", "activity", "wound", "nausea", "fever",
        "fear", "empathy", "family", "treatment", "weather", "generic",
    )
}


def lin_hao_response(response_id: str) -> tuple[str, str, str]:
    """Return one reviewed line as (text, emotion, intent)."""
    try:
        return LIN_HAO_RESPONSE_BANK[response_id]
    except KeyError:
        raise ValueError(f"unknown young-patient response id: {response_id}") from None


def lin_hao_response_catalog(recent_ids: list[str] | tuple[str, ...] = ()) -> str:
    """Compact model-facing catalogue; every sentence has cloned audio."""
    recent = set(recent_ids[-4:])
    lines = []
    for response_id, (text, emotion, intent) in LIN_HAO_RESPONSE_BANK.items():
        marker = "（最近已用，优先换一句）" if response_id in recent else ""
        lines.append(f"- {response_id} | {intent} | {emotion} | {text}{marker}")
    return "\n".join(lines)


def _first_fresh(intent: str, recent_ids: list[str] | tuple[str, ...]) -> str:
    candidates = [
        response_id for response_id, value in LIN_HAO_RESPONSE_BANK.items()
        if value[2] == intent
    ]
    recent = set(recent_ids[-4:])
    return next((item for item in candidates if item not in recent), candidates[0])


def select_lin_hao_response(
    question: str,
    recent_ids: list[str] | tuple[str, ...] = (),
) -> tuple[str, str, str, str]:
    """Safe local selector used only when the LLM selector is unavailable."""
    q = re.sub(r"\s+", "", question)
    if re.search(r"谢谢|辛苦了|先这样|明白了|知道了|结束|再见", q):
        intent = "closing"
    elif re.search(r"天气|下雨|晴天|新闻|明星|电影|球赛|股票|股市|游戏", q):
        intent = "irrelevant"
    elif re.search(r"我理解|理解您|别着急|我陪|陪着你|听你说|辛苦|会帮助", q):
        intent = "empathy"
    elif re.search(r"没事|休息.{0,4}就好|忍一忍|想太多|矫情|别大惊小怪", q):
        intent = "dismissal"
    elif re.search(r"我也不是医生|我又不是医生|我也不是大夫|我不知道|说不了|怎么具体", q):
        intent = "role_clarify"
    elif re.search(r"必须|赶紧|快点|别磨蹭|自己起来|直接下床", q):
        intent = "pressure"
    elif re.search(r"慢慢翻身|先坐|扶着你|陪你下床|有不舒服.{0,5}告诉|安全活动", q):
        intent = "activity_support"
    elif re.search(r"工作|职业|上班", q):
        intent = "work"
    elif re.search(r"名字|叫什么|几岁|年龄|多大", q):
        intent = "identity"
    elif re.search(r"为什么住院|什么病|阑尾炎|做了什么手术|什么手术", q):
        intent = "diagnosis"
    elif re.search(r"第一次住院|以前住过院", q):
        intent = "history"
    elif re.search(r"过敏|过敏史", q):
        intent = "allergy"
    elif re.search(r"生命体征|血压|心率|血氧|检查结果|化验|体温多少", q):
        intent = "vital"
    elif re.search(r"什么药|药量|止痛药|用药|吃药|打针|输液", q):
        intent = "medication"
    elif re.search(r"怎么治|治疗|诊断|是不是感染|是不是裂|需要手术", q):
        intent = "treatment"
    elif re.search(r"哪里不舒服|哪儿不舒服|怎么了|哪里难受|哪儿难受|什么感觉", q):
        intent = "opening"
    elif re.search(r"哪里疼|哪儿疼|疼痛|多疼|疼不疼|痛不痛|几分|程度|隐痛|切口疼|伤口疼", q):
        intent = "pain"
    elif re.search(r"什么时候|多久|多长时间|何时开始|什么时候开始", q):
        intent = "duration"
    elif re.search(r"下床|翻身|走动|活动|咳嗽|深呼吸", q):
        intent = "activity"
    elif re.search(r"伤口|切口|裂开|感染|出血|渗血|红肿", q):
        intent = "wound"
    elif re.search(r"恶心|呕吐|想吐|吐了", q):
        intent = "nausea"
    elif re.search(r"发热|发烧|发冷|体温", q):
        intent = "fever"
    elif re.search(r"最担心|最害怕|最怕|怕什么|担忧|担心|紧张", q):
        intent = "fear"
    elif re.search(r"家人|家属|父母|家里人|家里有|陪护|陪你|一个人", q):
        intent = "family"
    else:
        intent = "generic"
    response_id = _first_fresh(intent, recent_ids)
    text, emotion, _ = lin_hao_response(response_id)
    return response_id, text, emotion, intent


def select_lin_hao_reply(question: str) -> tuple[str, str, str]:
    response_id, reply, emotion, _ = select_lin_hao_response(question)
    return reply, emotion, response_id

def select_reply(question: str, case_id: str = "wang_ayi") -> tuple[str, str, str]:
    """只选择已知病例事实；未知话题仍用需求文档中的通用兜底语。"""
    if case_id == "human_candidate":
        return select_lin_hao_reply(question)
    q = re.sub(r"\s+", "", question)
    if re.search(r"癌|肿瘤|绝症|会不会死|要死|截肢|失明|瞎", q):
        category = "cancer"
    elif re.search(r"天气|下雨|晴天|新闻|明星|电影|球赛|股票|股市", q):
        category = "weather"
    elif re.search(r"哪里不舒服|哪儿不舒服|什么地方不舒服|怎么了|身体怎么样|哪里难受|哪儿难受", q):
        category = "opening"
    elif re.search(r"什么时候|多久|多长时间|从何时|什么时候开始|有几天", q):
        category = "duration_medication" if re.search(r"吃药|用药|什么药|有没有药|胰岛素", q) else "duration"
    elif re.search(r"怎么治|治疗|该吃什么药|换药|药量|胰岛素打多少|如何诊断|什么诊断", q):
        category = "treatment"
    elif re.search(r"什么药|吃药|用药|胰岛素|二甲双胍", q):
        category = "medication"
    elif re.search(r"如果.{0,8}伤口|有伤口.{0,8}告诉|发现伤口", q):
        category = "wound"
    elif re.search(r"洗脚|擦干|破损|破皮|伤口|足底|脚底|脚部护理|足部护理|看脚|鞋袜", q):
        category = "foot"
    elif re.search(r"饮食|吃饭|主食|甜食|少糖|饭菜|怎么吃|吃些|吃什么|早饭|晚饭", q):
        category = "diet"
    elif re.search(r"血糖多少|血糖大概|具体血糖|血糖数值|空腹血糖|糖化血红蛋白", q):
        category = "lab_values"
    elif re.search(r"血糖|测糖|监测|测过", q):
        category = "glucose"
    elif re.search(r"花钱|花费|费用|退休金|经济|住院费|负担", q):
        category = "cost"
    elif re.search(r"我理解|理解您|别着急|放心|陪您|听您说|辛苦|慢慢说", q):
        category = "empathy"
    elif re.search(r"最担心|最害怕|最怕|怕什么|担忧|担心|害怕|并发症|心里慌", q):
        category = "fear"
    elif re.search(r"家人|女儿|儿子|孩子|老伴|独居|一个人住|家里人", q):
        category = "family"
    elif re.search(r"散步|运动|活动|走动", q):
        category = "activity"
    elif re.search(r"既往史|以前有什么病|以前得过什么病|还有什么病", q):
        category = "history"
    else:
        category = "generic"
    reply, emotion = RESPONSES[category]
    return reply, emotion, category
