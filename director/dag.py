def parse_dag(self, tasks, payload=None, is_hook=False, src_parents=None, is_group=False):
    canvas_tasks = []
    parents = src_parents
    for task in tasks:
        if is_group:
            parents = src_parents
        if isinstance(task, dict):
            if "GROUP" in task:
                if not isinstance(task["GROUP"], list):
                    raise WorkflowSyntaxError()
                parents = parse_dag(task["GROUP"], payload,
                                    is_hook, parents,
                                    is_group=True)
            else:
                # add task
                ((task_name, condition),) = task.items()
                if payload is None or payload.get(condition, True):
                    parents = self.new_task(task_name, parents, is_hook)
        elif isinstance(task, list):
            parents = parse_dag(task, payload, is_hook, parents, is_group=False)
        elif isinstance(task, str):
            # add task
            parents = self.new_task(task, parents, is_hook)
        else:
            raise WorkflowSyntaxError()
        canvas_tasks.append(parents)
    if is_group:
        return group(*canvas_tasks, task_id=uuid())
    return chain(*canvas_tasks, task_id=uuid())
