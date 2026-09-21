from app.services.tools.calculator import calculate
from app.services.tools.datetime_tool import get_current_date_time
from app.services.tools.web_search import web_search

AVAILABLE_TOOLS = [calculate, get_current_date_time, web_search]
