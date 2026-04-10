export type CalendarEvent = {
  date: string;
  timeStart: string;
  timeEnd: string | null;
  studio: string | null;
  show: string;
  castType: string | null;
  notes: string | null;
};

function escapeIcs(value: string): string {
  return value
    .replace(/\\/g, "\\\\")
    .replace(/\r?\n/g, "\\n")
    .replace(/,/g, "\\,")
    .replace(/;/g, "\\;");
}

function toStamp(date: string, time: string): string {
  const hhmmss = `${time}:00`.slice(0, 8).replace(/:/g, "");
  return `${date.replace(/-/g, "")}T${hhmmss}`;
}

function addHour(time: string): string {
  const [hours, minutes] = time.split(":").map(Number);
  const nextHour = (hours + 1) % 24;
  return `${String(nextHour).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:00`;
}

export function buildCalendarFeed(events: CalendarEvent[]): string {
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//NBT Schedule Service//nbt.schedule//EN",
    "METHOD:PUBLISH",
    "X-WR-CALNAME:NBT Full Schedule",
    "X-WR-TIMEZONE:America/Los_Angeles",
    "CALSCALE:GREGORIAN",
  ];

  for (const event of events) {
    const endTime = event.timeEnd ?? addHour(event.timeStart);
    const uid = [
      "nbt",
      event.date,
      event.timeStart.slice(0, 5).replace(":", ""),
      event.show.toUpperCase().replaceAll(" ", "-").replaceAll("/", "-"),
    ].join("-") + "@nbt.schedule";

    const descriptionParts: string[] = [];
    if (event.castType?.trim()) {
      descriptionParts.push(`Cast: ${event.castType.trim()}`);
    }
    if (event.notes?.trim()) {
      descriptionParts.push(`Notes: ${event.notes.trim()}`);
    }

    lines.push(
      "BEGIN:VEVENT",
      `UID:${escapeIcs(uid)}`,
      `DTSTART;TZID=America/Los_Angeles:${toStamp(event.date, event.timeStart)}`,
      `DTEND;TZID=America/Los_Angeles:${toStamp(event.date, endTime.slice(0, 8))}`,
      `SUMMARY:${escapeIcs(event.show)}`,
      `LOCATION:${escapeIcs(event.studio ? `Studio ${event.studio}` : "NBT")}`,
      ...(descriptionParts.length > 0 ? [`DESCRIPTION:${escapeIcs(descriptionParts.join("\n"))}`] : []),
      "SEQUENCE:1",
      "END:VEVENT",
    );
  }

  lines.push("END:VCALENDAR");
  return lines.join("\r\n");
}
