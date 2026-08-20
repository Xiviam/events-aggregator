"""HTTP integration with the Events Provider API."""

from events_aggregator.provider.client import EventsProviderClient
from events_aggregator.provider.paginator import EventsPaginator

__all__ = ["EventsPaginator", "EventsProviderClient"]
