// The core is loaded with this file's version query so an update never pairs a
// new card with a cached old core.
const { defineTouCard } = await import(`./tou-card-core.js${new URL(import.meta.url).search}`);

// The cloud reports times as HHMM ("0100"); the card works in HH:MM.
const time = (value) => {
  const digits = String(value ?? "").replace(":", "").padStart(4, "0");
  return `${digits.slice(0, 2)}:${digits.slice(2, 4)}`;
};

defineTouCard({
  domain: "deye_cloud",
  type: "deye-cloud-tou-card",
  name: "Deye Cloud Time Of Use",
  description: "The inverter's Time Of Use table, edited like on its screen and saved in one write.",
  documentationURL: "https://github.com/maxbanton/hass-deye-cloud#time-of-use-card",
  readSchedule: (slots) =>
    slots.map((slot) => ({
      time: time(slot.time),
      power: slot.power,
      batt: slot.soc,
      grid_charge: !!slot.enableGridCharge,
      gen: !!slot.enableGeneration,
    })),
  pendingMs: 300000,
  minuteStep: 5,
});
