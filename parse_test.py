import yaml
import pprint

def _transform_yaml(data):
    result = {}
    for model_version, tasks in data.items():
        if not tasks:
            continue
        for task, subtasks in tasks.items():
            key = f"{model_version}:{task}"
            result[key] = subtasks
    return result

path = "./dags.yaml"
with open(path) as f:
    workflows = yaml.load(f, Loader=yaml.SafeLoader)

formatted_dict = _transform_yaml(workflows)
pprint.pprint(formatted_dict)

# test_list = formatted_dict["v2.0-20240919:image2model"]
# pprint.pprint(test_list)