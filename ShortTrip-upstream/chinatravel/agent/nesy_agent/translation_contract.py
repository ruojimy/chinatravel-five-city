"""Validate translated constraint programs before spending time on DFS."""
import ast
import json
from numpy import bool_ as numpy_bool
from urllib.parse import urlsplit
from chinatravel.symbol_verification.dsl import execute_dsl_code, validate_dsl_code


class TranslationValidationError(ValueError):
    pass


def extraction_output_options(llm):
    url=getattr(llm,'_client_kwargs',{}).get('base_url','')
    if urlsplit(str(url)).hostname not in ('localhost','127.0.0.1','::1'):
        return {}
    evidence={'type':'array','items':{'type':'object',
        'properties':{'constraint':{'type':'string'},'source':{'type':'string'}},
        'required':['constraint','source'],'additionalProperties':False}}
    strings={'type':'array','items':{'type':'string'}}
    schema={'type':'object','properties':{
        'hard_logic':strings,'hard_logic_evidence':evidence,
        'soft_logic':strings,'soft_logic_evidence':evidence},
        'required':['hard_logic','hard_logic_evidence','soft_logic','soft_logic_evidence'],
        'additionalProperties':False}
    return {'response_format':{'type':'json_schema','json_schema':{
        'name':'extracted_requirements','strict':True,'schema':schema}}}


def output_options(llm,count):
    """Use llama.cpp's schema grammar locally; keep cloud compatibility."""
    url=getattr(llm,'_client_kwargs',{}).get('base_url','')
    if urlsplit(str(url)).hostname not in ('localhost','127.0.0.1','::1'):
        return {}
    schema={'type':'object','properties':{'hard_logic_py':{
        'type':'array','items':{'type':'string'},'minItems':count,'maxItems':count}},
        'required':['hard_logic_py'],'additionalProperties':False}
    return {'response_format':{'type':'json_schema','json_schema':{
        'name':'constraint_programs','strict':True,'schema':schema}}}


CODE_OUTPUT_INSTRUCTION = '''
OUTPUT CONTRACT (overrides the illustrative output format above):
Translate the constraints into Python checking programs, NOT a travel itinerary.
Return exactly one JSON object: {"hard_logic_py": ["result=(day_count(plan)==2)"]}.
The example is format only; use the actual requirements supplied below.
Every list item must be a Python source STRING. Every program must read plan
using the documented functions and explicitly assign a BOOLEAN to result.
Never output activity dictionaries, bare comparisons, result=True alone, an
empty list, invented hotels/times/requirements, or omit a supplied constraint.
Produce EXACTLY one program for each supplied constraint, in the SAME order.
Do not merge constraints or append unrelated checks. Preserve all valid
constraints when repairing. If a requirement cannot be translated, explain the
error instead of returning an empty or weaker constraint list.
'''

PROGRAM_EXAMPLES = '''
Small example (different input; copy the code pattern, never its numbers):
Input constraints: ["days==3", "people_number==3", "tickets==3", "taxi_cars==1", "intercity_transport=={'train'}"]
Output:
{"hard_logic_py": [
"result=(day_count(plan)==3)",
"result=(people_count(plan)==3)",
"result=True\\nfor activity in allactivities(plan):\\n  if activity_type(activity) in ['attraction','train','airplane'] and activity_tickets(activity)!=3: result=False\\n  for leg in activity_transports(activity):\\n    if leg['mode']=='metro' and metro_tickets(activity_transports(activity))!=3: result=False",
"result=True\\nfor activity in allactivities(plan):\\n  for leg in activity_transports(activity):\\n    if leg['mode']=='taxi' and taxi_cars(activity_transports(activity))!=1: result=False",
"modes=set()\\nfor activity in allactivities(plan):\\n  if activity_type(activity) in ['train','airplane']: modes.add(activity_type(activity))\\nresult=(modes=={'train'})"
]}
Do not inspect only allactivities(plan)[0]. Do not use invented functions or
Python assignment expressions (:=). taxi_cars and metro_tickets take a
transport list from activity_transports(activity), NOT plan or one leg.
Only check taxi_cars/metro_tickets when that mode actually occurs in the legs.
'''


def code_list(response):
    text=response.strip()
    if text.startswith('```'):
        text='\n'.join(text.splitlines()[1:-1])
    try:
        value=json.loads(text)
    except (TypeError,ValueError) as exc:
        raise TranslationValidationError('Translation must be valid JSON') from exc
    if isinstance(value,dict):
        value=value.get('hard_logic_py')
    if not isinstance(value,list) or not value or any(not isinstance(c,str) or not c.strip() for c in value):
        raise TranslationValidationError('Translation hard_logic_py must be a nonempty list of Python strings, not itinerary dictionaries')
    return value


def check_constraint(code,variables):
    if not isinstance(code,str) or not code.strip():
        raise TranslationValidationError('Translation program must be a nonempty Python string')
    tree=validate_dsl_code(code,allowed_names=set(variables))
    list_variables=set()
    leg_variables=set()
    for node in ast.walk(tree):
        if (isinstance(node,ast.Assign) and isinstance(node.value,ast.Call)
                and isinstance(node.value.func,ast.Name) and node.value.func.id=='activity_transports'):
            list_variables.update(t.id for t in node.targets if isinstance(t,ast.Name))
    for node in ast.walk(tree):
        if isinstance(node,ast.For) and isinstance(node.target,ast.Name):
            iterator=node.iter
            if ((isinstance(iterator,ast.Call) and isinstance(iterator.func,ast.Name) and iterator.func.id=='activity_transports')
                    or (isinstance(iterator,ast.Name) and iterator.id in list_variables)):
                leg_variables.add(node.target.id)
    for node in ast.walk(tree):
        if (isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
                and node.func.id in {'metro_tickets','taxi_cars','innercity_transport_cost','innercity_transport_type','innercity_transport_time'}
                and node.args and isinstance(node.args[0],ast.Name) and node.args[0].id in leg_variables|{'plan'}):
            raise TranslationValidationError(f'{node.func.id}(transports: list[dict]) received {node.args[0].id}; use activity_transports(activity), not one leg or plan')
    # A top-level initialization makes result available even when loops are empty.
    if not any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='result' for t in n.targets)
               for n in tree.body):
        raise TranslationValidationError('Translation program must explicitly assign boolean result at top level')
    if not any(isinstance(n,ast.Name) and n.id=='plan' and isinstance(n.ctx,ast.Load) for n in ast.walk(tree)):
        raise TranslationValidationError('Translation must check plan, not return a constant or an itinerary')
    variables.pop('result',None)
    execute_dsl_code(code,variables,allowed_builtins={'set':set})
    if not isinstance(variables.get('result'),(bool,numpy_bool)):
        raise TranslationValidationError('Translation program must produce a boolean result (True or False)')
