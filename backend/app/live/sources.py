"""
Official source registry: which hosts are official government sources, what kind
(national portal, ministry / department, state), and how long a page from them may be
reused from cache (source-specific refresh policy).

Classification uses the parsed hostname — never a substring of the URL — so
"https://evil.example/?x=.gov.in" is not official. Hosts under gov.in / nic.in (reserved for
Indian government bodies) are official; a few official sites outside those zones are listed
explicitly, and hosts of the stored, verified scheme sources are added at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set
from urllib.parse import urlsplit

from app.services.change_detection import url as _canonical

NATIONAL_PORTAL, MINISTRY, STATE, OFFICIAL_OTHER, SECONDARY, UNKNOWN = (
    "NATIONAL_PORTAL", "MINISTRY", "STATE", "OFFICIAL_OTHER", "SECONDARY", "UNKNOWN")
OFFICIAL_CATEGORIES = {NATIONAL_PORTAL, MINISTRY, STATE, OFFICIAL_OTHER}

NATIONAL_PORTALS: Dict[str, str] = {
    "myscheme.gov.in": "myScheme (national scheme portal)",
    "india.gov.in": "National Portal of India",
}

# Central ministries / departments / scheme portals relevant to farmers.
MINISTRY_HOSTS: Dict[str, str] = {
    "agriwelfare.gov.in": "Department of Agriculture & Farmers Welfare",
    "agricoop.nic.in": "Department of Agriculture & Farmers Welfare (old site)",
    "pmkisan.gov.in": "PM-KISAN portal", "pmfby.gov.in": "PM Fasal Bima Yojana portal",
    "pmksy.gov.in": "PM Krishi Sinchayee Yojana", "enam.gov.in": "e-NAM",
    "midh.gov.in": "Mission for Integrated Development of Horticulture", "nfsm.gov.in": "NFSM",
    "soilhealth.dac.gov.in": "Soil Health Card", "agriinfra.dac.gov.in": "Agriculture Infrastructure Fund",
    "nmsa.dac.gov.in": "NMSA", "agrimachinery.nic.in": "Farm machinery (SMAM)", "rkvy.nic.in": "RKVY",
    "nbm.nic.in": "National Bamboo Mission", "dahd.nic.in": "Department of Animal Husbandry & Dairying",
    "dahd.gov.in": "Department of Animal Husbandry & Dairying", "rural.gov.in": "Ministry of Rural Development",
    "nrega.nic.in": "MGNREGA", "nrlm.gov.in": "DAY-NRLM", "pmayg.nic.in": "PMAY-Gramin",
    "jansuraksha.gov.in": "Jan Suraksha schemes", "pmjdy.gov.in": "PM Jan Dhan Yojana",
    "agmarknet.gov.in": "AGMARKNET", "mofpi.gov.in": "Ministry of Food Processing Industries",
    "pib.gov.in": "Press Information Bureau", "maandhan.in": "PM Kisan Maan-Dhan (official portal)",
    "nabard.org": "NABARD",
}

# State agriculture / welfare portals, by state (used to scope discovery to the farmer's state).
STATE_HOSTS: Dict[str, List[str]] = {
    "Karnataka": ["raitamitra.karnataka.gov.in", "karnataka.gov.in", "fruits.karnataka.gov.in"],
    "Maharashtra": ["krishi.maharashtra.gov.in", "mahadbt.maharashtra.gov.in", "nsmny.mahait.org"],
    "Tamil Nadu": ["tnagrisnet.tn.gov.in", "tn.gov.in"],
    "Telangana": ["agri.telangana.gov.in", "rythubandhu.telangana.gov.in", "telangana.gov.in"],
    "Andhra Pradesh": ["apagrisnet.gov.in", "ysrrythubharosa.ap.gov.in", "ap.gov.in"],
    "Uttar Pradesh": ["agriculture.up.gov.in", "upagripardarshi.gov.in", "up.gov.in"],
    "Punjab": ["agri.punjab.gov.in", "punjab.gov.in"],
    "Rajasthan": ["agriculture.rajasthan.gov.in", "rajkisan.rajasthan.gov.in", "rajasthan.gov.in"],
    "Madhya Pradesh": ["mpkrishi.mp.gov.in", "mp.gov.in"],
    "Gujarat": ["ikhedut.gujarat.gov.in", "agri.gujarat.gov.in", "gujarat.gov.in"],
    "Bihar": ["dbtagriculture.bihar.gov.in", "state.bihar.gov.in"],
    "West Bengal": ["wb.gov.in", "wbagrimarketingboard.gov.in"],
    "Odisha": ["agriodisha.nic.in", "odisha.gov.in"],
    "Kerala": ["keralaagriculture.gov.in", "kerala.gov.in"],
    "Haryana": ["agriharyana.gov.in", "haryana.gov.in"],
}
_STATE_HOST_SET = {h for hosts in STATE_HOSTS.values() for h in hosts}
_OFFICIAL_SUFFIXES = (".gov.in", ".nic.in")
_SECONDARY_HOSTS = {"vikaspedia.in"}

# How long a successfully fetched page may be reused before it must be fetched again.
TTL_SECONDS = {NATIONAL_PORTAL: 12 * 3600, MINISTRY: 24 * 3600, STATE: 24 * 3600, OFFICIAL_OTHER: 12 * 3600}
PDF_TTL_SECONDS = 7 * 24 * 3600            # guidelines PDFs change rarely
FAILURE_TTL_SECONDS = 30 * 60              # don't hammer a source that just failed


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def canonical_url(url: str) -> Optional[str]:
    """Stable key for de-duplication (host without www, no scheme / fragment / tracking params)."""
    return _canonical(url)


def _under(host: str, root: str) -> bool:
    return host == root or host.endswith("." + root)


@dataclass(frozen=True)
class SourceInfo:
    host: str
    category: str
    label: str

    @property
    def official(self) -> bool:
        return self.category in OFFICIAL_CATEGORIES


class Registry:
    """Classifies URLs; learns extra official hosts from the stored, verified corpus."""

    def __init__(self, extra_official_hosts: Iterable[str] = ()):
        self.extra: Set[str] = {h.lower().removeprefix("www.") for h in extra_official_hosts if h}

    def add_official_hosts(self, hosts: Iterable[str]) -> None:
        self.extra |= {h.lower().removeprefix("www.") for h in hosts if h}

    def classify(self, url: str) -> SourceInfo:
        host = host_of(url)
        if not host or not url.lower().startswith(("http://", "https://")):
            return SourceInfo(host, UNKNOWN, "Not a web address")
        for root, label in NATIONAL_PORTALS.items():
            if _under(host, root):
                return SourceInfo(host, NATIONAL_PORTAL, label)
        for root, label in MINISTRY_HOSTS.items():
            if _under(host, root):
                return SourceInfo(host, MINISTRY, label)
        for root in _STATE_HOST_SET:
            if _under(host, root):
                return SourceInfo(host, STATE, "State government portal")
        if host.endswith(_OFFICIAL_SUFFIXES) or any(_under(host, h) for h in self.extra):
            return SourceInfo(host, OFFICIAL_OTHER, "Government website")
        if any(_under(host, h) for h in _SECONDARY_HOSTS):
            return SourceInfo(host, SECONDARY, "Government-supported information site")
        return SourceInfo(host, UNKNOWN, "Not an official government source")

    def ttl(self, url: str, content_type: str = "") -> int:
        if "pdf" in (content_type or "").lower() or url.lower().split("?")[0].endswith(".pdf"):
            return PDF_TTL_SECONDS
        return TTL_SECONDS.get(self.classify(url).category, 6 * 3600)


def discovery_domains(state: Optional[str]) -> Dict[str, List[str]]:
    """Domain groups to scope live search to (one search per group)."""
    groups = {"national": list(NATIONAL_PORTALS),
              "ministry": ["agriwelfare.gov.in", "pmkisan.gov.in", "pmfby.gov.in", "pib.gov.in", "rural.gov.in",
                           "dahd.gov.in", "pmksy.gov.in", "enam.gov.in"]}
    for name, hosts in STATE_HOSTS.items():
        if state and name.lower() == state.strip().lower():
            groups["state"] = hosts
    return groups


registry = Registry()
