"""Business logic of the clinic: doctors, availability and appointments.

Kept apart from the protocol layer in :mod:`clinic_server.server`, so the rules
below can be read (and tested) without thinking about JSON-RPC.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CATALOG_FILE = os.path.join(DATA_DIR, "clinic.json")
APPOINTMENTS_FILE = os.path.join(DATA_DIR, "appointments.json")

DATE_FORMAT = "%Y-%m-%d"


class ClinicError(Exception):
    """A request the clinic cannot satisfy (bad input, slot taken, ...).

    These are business errors, not protocol errors: the server answers with a
    normal MCP result carrying ``isError``, so the model can read the reason
    and try again.
    """


class ClinicStore:
    """Reads the catalogue and keeps the appointments file up to date."""

    def __init__(self, catalog_file: str = CATALOG_FILE,
                 appointments_file: str = APPOINTMENTS_FILE) -> None:
        self.appointments_file = appointments_file
        with open(catalog_file, encoding="utf-8") as handle:
            catalog = json.load(handle)
        self.clinic = catalog["clinic"]
        self.specialties = catalog["specialties"]
        self.doctors = catalog["doctors"]
        self.appointments = self._load_appointments()

    def _load_appointments(self) -> list[dict]:
        if not os.path.exists(self.appointments_file):
            return []
        with open(self.appointments_file, encoding="utf-8") as handle:
            return json.load(handle)

    def _save_appointments(self) -> None:
        os.makedirs(os.path.dirname(self.appointments_file), exist_ok=True)
        with open(self.appointments_file, "w", encoding="utf-8") as handle:
            json.dump(self.appointments, handle, indent=2, ensure_ascii=False)

    # -- lookups ---------------------------------------------------------- #
    def list_specialties(self) -> list[dict]:
        return self.specialties

    def find_doctors(self, specialty: str | None = None,
                     name: str | None = None) -> list[dict]:
        """Filter doctors by specialty id or name, and/or by doctor name."""
        found = self.doctors
        if specialty:
            key = specialty.strip().lower()
            valid = {s["id"] for s in self.specialties}
            if key not in valid:
                # Accept the display name too ("Cardiologia").
                match = [s["id"] for s in self.specialties
                         if s["name"].lower() == key]
                if not match:
                    raise ClinicError(
                        f"Unknown specialty '{specialty}'. "
                        f"Valid ids: {', '.join(sorted(valid))}.")
                key = match[0]
            found = [d for d in found if d["specialty"] == key]
        if name:
            needle = name.strip().lower()
            found = [d for d in found if needle in d["name"].lower()]
        return found

    def get_doctor(self, doctor_id: str) -> dict:
        for doctor in self.doctors:
            if doctor["id"] == doctor_id:
                return doctor
        raise ClinicError(f"Unknown doctor '{doctor_id}'. "
                          f"Use find_doctors to get a valid id.")

    # -- availability ----------------------------------------------------- #
    def get_availability(self, doctor_id: str, date: str) -> dict:
        """Free slots of a doctor on a date, in ISO format (YYYY-MM-DD)."""
        doctor = self.get_doctor(doctor_id)
        weekday = _parse_date(date).strftime("%A").lower()
        if weekday not in doctor["days"]:
            return {"doctor_id": doctor_id, "doctor": doctor["name"],
                    "date": date, "weekday": weekday, "available": [],
                    "note": f"{doctor['name']} does not work on {weekday}s."}

        taken = {a["time"] for a in self.appointments
                 if a["doctor_id"] == doctor_id and a["date"] == date
                 and a["status"] == "confirmed"}
        return {"doctor_id": doctor_id, "doctor": doctor["name"],
                "date": date, "weekday": weekday,
                "available": [h for h in doctor["hours"] if h not in taken]}

    # -- appointments ----------------------------------------------------- #
    def book_appointment(self, doctor_id: str, date: str, time: str,
                         patient_name: str, reason: str = "") -> dict:
        """Book a free slot and return the appointment with its code."""
        doctor = self.get_doctor(doctor_id)
        if time not in self.get_availability(doctor_id, date)["available"]:
            raise ClinicError(
                f"{doctor['name']} is not available on {date} at {time}. "
                f"Check get_availability for the free slots.")
        if not patient_name.strip():
            raise ClinicError("patient_name cannot be empty.")

        appointment = {
            "code": f"APT-{secrets.token_hex(3).upper()}",
            "doctor_id": doctor_id,
            "doctor": doctor["name"],
            "specialty": doctor["specialty"],
            "office": doctor["office"],
            "date": date,
            "time": time,
            "patient_name": patient_name.strip(),
            "reason": reason.strip(),
            "status": "confirmed",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.appointments.append(appointment)
        self._save_appointments()
        return appointment

    def get_appointment(self, code: str) -> dict:
        for appointment in self.appointments:
            if appointment["code"] == code.strip().upper():
                return appointment
        raise ClinicError(f"No appointment with code '{code}'.")

    def cancel_appointment(self, code: str) -> dict:
        appointment = self.get_appointment(code)
        if appointment["status"] == "cancelled":
            raise ClinicError(f"Appointment {appointment['code']} "
                              f"was already cancelled.")
        appointment["status"] = "cancelled"
        appointment["cancelled_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_appointments()
        return appointment


def _parse_date(date: str) -> datetime:
    try:
        return datetime.strptime(date.strip(), DATE_FORMAT)
    except ValueError:
        raise ClinicError(f"Invalid date '{date}'. Use the format YYYY-MM-DD.") from None
