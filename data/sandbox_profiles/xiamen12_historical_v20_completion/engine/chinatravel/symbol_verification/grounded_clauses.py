"""Extend recognized, audited hard-clause templates with grounded evidence."""
import ast
import re

from catalog_completion import category_value, cuisine_value

from chinatravel.symbol_verification.grounded_places import attraction_types, visit_names


_CATEGORY = """attraction_type_set=set()
for activity in allactivities(plan):
  if activity_type(activity)=='attraction': attraction_type_set.add(attraction_type(activity, target_city(plan)))
result=({required}<=attraction_type_set)"""
_CUISINE = """restaurant_type_set=set()
for activity in allactivities(plan):
  if activity_type(activity) in ['breakfast', 'lunch', 'dinner']: restaurant_type_set.add(restaurant_type(activity, target_city(plan)))
result=({required}<=restaurant_type_set)"""
_RESTAURANT = """restaurant_name_set=set()
for activity in allactivities(plan):
  if activity_type(activity) in ['breakfast', 'lunch', 'dinner']: restaurant_name_set.add(activity_position(activity))
result=({required}<=restaurant_name_set)"""
_ATTRACTION = """result=False
for a in allactivities(plan):
  if activity_type(a)=='attraction' and activity_position(a)=={required}: result=True"""


def _extract(template, clause):
    before, after = template.split('{required}')
    match = re.fullmatch(re.escape(before) + r'(.+)' + re.escape(after), clause)
    if match:
        try:
            return ast.literal_eval(match[1])
        except (ValueError, SyntaxError):
            pass
    return None


def grounded_clause(key, clause, plan, functions, city):
    """Return None for unrecognized DSL so the original evaluator handles it."""
    activities = functions['allactivities'](plan)
    if key == 'required_attraction_types':
        required = _extract(_CATEGORY, clause)
        if isinstance(required, set) and all(isinstance(x, str) for x in required):
            found = set()
            for a in activities:
                if a.get('type') == 'attraction':
                    labels = functions['attraction_category_values'](a, city)
                    legacy = attraction_types(a, city, functions['attraction_type'](a, city))
                    found.update(category_value(label) for label in [*labels, *legacy])
            return {category_value(label) for label in required} <= found
    elif key in ('required_restaurant_types', 'required_cuisines', 'restaurant_type', 'cuisine', 'restaurant_cuisine'):
        required = _extract(_CUISINE, clause)
        if isinstance(required, set) and all(isinstance(x, str) for x in required):
            labels = [functions['restaurant_cuisine_values'](a, city) for a in activities
                      if a.get('type') in ('breakfast', 'lunch', 'dinner')]
            if {cuisine_value(label) for label in required} <= {label for values in labels for label in values}:
                return True
            if any(not values for values in labels):
                raise ValueError('Cuisine evidence missing for a meal venue')
            return False
    elif key == 'required_restaurant_names':
        required = _extract(_RESTAURANT, clause)
        if isinstance(required, set) and all(isinstance(x, str) for x in required):
            found = set()
            for a in activities:
                if a.get('type') in ('breakfast', 'lunch', 'dinner'):
                    found.update(visit_names(city, 'restaurant', a.get('position')))
            return required <= found
    elif key.startswith('指定景点 '):
        required = _extract(_ATTRACTION, clause)
        if required == key.removeprefix('指定景点 '):
            return any(required in visit_names(city, 'attraction', a.get('position'))
                       for a in activities if a.get('type') == 'attraction')
    return None
