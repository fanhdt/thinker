from app.models.goal import Goal


def build_personalization_context(goals: list[Goal], preferences: dict) -> str:
    parts = []

    if preferences:
        pref_lines = "\n".join(f"= {key}:{value}" for key, value in preferences.items())
        parts.append(f"Preferensi user (ikuti ini dalam menjawab):\n{pref_lines}")

    if goals:
        goal_lines = "\n".join(f"- {g.description}" for g in goals)
        parts.append(f"Tujuan jangka panjang user yang sedang aktif:\n{goal_lines}")

    return "\n\n".join(parts)
