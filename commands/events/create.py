from datetime import datetime, timedelta
def GenerateProposedDates(target: str = None):
    today = datetime.now().date()

    if target:
        target_date = datetime.strptime(target, "%m/%d/%y").date()
        if target_date < today:
            return None
    else:
        target_date = today

    # Start of week = Sunday
    calendar_start = target_date - timedelta(days=(target_date.weekday() + 1) % 7)

    return [
        (calendar_start + timedelta(days=i)).strftime("%A, %m/%d/%y")
        for i in range(14)
    ]


