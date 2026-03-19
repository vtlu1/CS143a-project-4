### Fill in the following information before submitting
# Group id: 12
# Members: Vincent Lu, Jayce Spurgiasz, Jacob Soryal

from collections import deque
from dataclasses import dataclass

PID = int

BACKGROUND: str = "Background"
FOREGROUND: str = "Foreground"


class PCB:
    pid: PID
    priority: int
    num_quantum_ticks: int
    process_type: str
    
    def __init__(self, pid: PID, priority: int, process_type: str):
        self.pid = pid
        self.priority = priority
        self.num_quantum_ticks = 0
        self.process_type = process_type
    def __str__(self):
        return f"({self.pid}, {self.priority})"
    def __repr__(self):
        return f"({self.pid}, {self.priority})"


RR_QUANTUM_TICKS: int = 4
ACTIVE_QUEUE_NUM_TICKS: int = 20

MULTILEVEL: str = "Multilevel"
RR: str = "RR"
FCFS: str = "FCFS"
PRIORITY: str = "Priority"


class Kernel:
    scheduling_algorithm: str
    ready_queue: deque[PCB]
    waiting_queue: deque[PCB]
    running: PCB
    idle_pcb: PCB
    fcfs_ready_queue: deque[PCB]
    rr_ready_queue: deque[PCB]
    active_queue: str
    active_queue_num_ticks: int

    def __init__(self, scheduling_algorithm: str, logger, mmu: "MMU", memory_size: int):
        self.scheduling_algorithm = scheduling_algorithm
        self.ready_queue = deque()
        self.waiting_queue = deque()
        self.idle_pcb = PCB(0, 0, "Foreground")
        self.running = self.idle_pcb
        self.logger = logger

        self.mmu = mmu
        self.memory_size = memory_size

        self.fcfs_ready_queue = deque()
        self.rr_ready_queue = deque()
        self.active_queue = FOREGROUND
        self.active_queue_num_ticks = 0

        self.semaphores = {}
        self.mutexes = {}

        self.free_list = [(10 * 1024 * 1024, memory_size)]  # (start, size)
        self.process_memory = {}

    def new_process_arrived(self, new_process: PID, priority: int, process_type: str, stack_memory_needed: int, heap_memory_needed: int) -> PID:
        stack_bytes = stack_memory_needed
        heap_bytes = heap_memory_needed

        stack_alloc = self.best_fit_allocate(stack_bytes)
        if stack_alloc is None:
            return -1

        heap_alloc = None
        if heap_bytes > 0:
            heap_alloc = self.best_fit_allocate(heap_bytes)
            if heap_alloc is None:
                self.free_memory(stack_alloc[0], stack_alloc[1])
                return -1

        self.process_memory[new_process] = {
            "stack_base": stack_alloc[0],
            "stack_size": stack_alloc[1],
            "heap_base": heap_alloc[0] if heap_alloc else None,
            "heap_size": heap_alloc[1] if heap_alloc else 0
        }

        self.mmu.process_memory = self.process_memory

        self.ready_queue.append(PCB(new_process, priority, process_type))

        if self.scheduling_algorithm == MULTILEVEL and self.running is self.idle_pcb:
            self.active_queue_num_ticks = 0

        self.choose_next_process()
        return self.running.pid

    def syscall_exit(self) -> PID:
        pid = self.running.pid

        if pid in self.process_memory:
            mem = self.process_memory[pid]
            self.free_memory(mem["stack_base"], mem["stack_size"])
            if mem["heap_size"] > 0:
                self.free_memory(mem["heap_base"], mem["heap_size"])
            del self.process_memory[pid]

        self.running = self.idle_pcb
        self.choose_next_process()
        return self.running.pid

    def syscall_set_priority(self, new_priority: int) -> PID:
        self.running.priority = new_priority
        self.choose_next_process()
        return self.running.pid

    def choose_next_process(self):
        if self.scheduling_algorithm == FCFS:
            self.fcfs_chose_next_process(self.ready_queue)

        elif self.scheduling_algorithm == PRIORITY:
            if len(self.ready_queue) == 0:
                return
            if self.running is not self.idle_pcb:
                self.ready_queue.append(self.running)
            next_process = pop_min_priority(self.ready_queue)
            self.running = next_process
        elif self.scheduling_algorithm == RR:
            self.rr_chose_next_process(self.ready_queue)

        elif self.scheduling_algorithm == MULTILEVEL:
            while len(self.ready_queue) > 0:
                pcb = self.ready_queue.popleft()
                if pcb.process_type == FOREGROUND:
                    self.rr_ready_queue.append(pcb)
                elif pcb.process_type == BACKGROUND:
                    self.fcfs_ready_queue.append(pcb)
            if self.active_queue == FOREGROUND:
                self.rr_chose_next_process(self.rr_ready_queue)
            elif self.active_queue == BACKGROUND:
                self.fcfs_chose_next_process(self.fcfs_ready_queue)
            if self.running is self.idle_pcb:
                self.switch_active_queue()

                if self.active_queue == FOREGROUND:
                    self.rr_chose_next_process(self.rr_ready_queue)
                elif self.active_queue == BACKGROUND:
                    self.fcfs_chose_next_process(self.fcfs_ready_queue)

    def rr_chose_next_process(self, queue: deque[PCB]):
        if self.running is self.idle_pcb:
            if len(queue) == 0:
                return
            self.running = queue.popleft()

        elif exceeded_quantum(self.running):
            queue.append(self.running)
            self.running = queue.popleft()

    def fcfs_chose_next_process(self, queue: deque[PCB]):
        if len(queue) == 0:
            return

        if self.running is self.idle_pcb:
            self.running = queue.popleft()

    def switch_active_queue(self):
        self.active_queue_num_ticks = 0

        if self.active_queue == FOREGROUND:
            if len(self.fcfs_ready_queue) == 0:
                return
            if self.running is not self.idle_pcb:
                if exceeded_quantum(self.running):
                    self.rr_ready_queue.append(self.running)
                else:
                    self.rr_ready_queue.appendleft(self.running)
                self.running = self.idle_pcb
            self.active_queue = BACKGROUND

        elif self.active_queue == BACKGROUND:
            if len(self.rr_ready_queue) == 0:
                return
            if self.running is not self.idle_pcb:
                self.fcfs_ready_queue.appendleft(self.running)
                self.running = self.idle_pcb
            self.active_queue = FOREGROUND

    def timer_interrupt(self) -> PID:
        self.running.num_quantum_ticks += 1
        self.active_queue_num_ticks += 1

        if self.scheduling_algorithm == RR:
            self.choose_next_process()
        elif self.scheduling_algorithm == MULTILEVEL:
            if self.active_queue_num_ticks >= ACTIVE_QUEUE_NUM_TICKS:
                self.switch_active_queue()
            self.choose_next_process()

        return self.running.pid

    # semaphores
    def syscall_init_semaphore(self, semaphore_id: int, initial_value: int):
        self.semaphores[semaphore_id] = {"value": initial_value, "waiting": []}

    def syscall_semaphore_p(self, semaphore_id: int) -> PID:
        a_sem = self.semaphores[semaphore_id]
        a_sem["value"] -= 1
        if a_sem["value"] < 0:
            a_sem["waiting"].append(self.running)
            self.running = self.idle_pcb
            self.choose_next_process()

        return self.running.pid

    def syscall_semaphore_v(self, semaphore_id: int) -> PID:
        a_sem = self.semaphores[semaphore_id]
        a_sem["value"] += 1

        if a_sem["value"] <= 0 and len(a_sem["waiting"]) > 0:
            if self.scheduling_algorithm == PRIORITY:
                returned_process = pop_min_priority(a_sem["waiting"])
            else:
                returned_process = pop_min_pid(a_sem["waiting"])
            returned_process.num_quantum_ticks = 0
            self.ready_queue.append(returned_process)
            if self.scheduling_algorithm == PRIORITY:
                self.choose_next_process()

        return self.running.pid

    # mutexes
    def syscall_init_mutex(self, mutex_id: int):
        self.mutexes[mutex_id] = {"lock": False, "owner": None, "waiting": []}

    def syscall_mutex_lock(self, mutex_id: int) -> PID:
        mutex = self.mutexes[mutex_id]
        if not mutex["lock"]:
            mutex["lock"] = True
            mutex["owner"] = self.running.pid
        else:
            mutex["waiting"].append(self.running)
            self.running = self.idle_pcb
            self.choose_next_process()

        return self.running.pid

    def syscall_mutex_unlock(self, mutex_id: int) -> PID:
        mutex = self.mutexes[mutex_id]
        if len(mutex["waiting"]) > 0:
            if self.scheduling_algorithm == PRIORITY:
                returned_process = pop_min_priority(mutex["waiting"])
            else:
                returned_process = pop_min_pid(mutex["waiting"])
            self.ready_queue.append(returned_process)
            mutex["owner"] = returned_process.pid
            mutex["lock"] = True

            if self.scheduling_algorithm == PRIORITY:
                self.choose_next_process()
        else:
            mutex["lock"] = False
            mutex["owner"] = None

        return self.running.pid

    def best_fit_allocate(self, size):
        best_index = -1
        best_size = float('inf')
        for i, (start, hole_size) in enumerate(self.free_list):
            if hole_size >= size and hole_size < best_size:
                best_index = i
                best_size = hole_size
        if best_index == -1:
            return None

        start, hole_size = self.free_list[best_index]
        alloc_start = start
        remaining = hole_size - size
        if remaining > 0:
            self.free_list[best_index] = (start + size, remaining)
        else:
            self.free_list.pop(best_index)
        return (alloc_start, size)

    def free_memory(self, start, size):
        self.free_list.append((start, size))
        self.free_list.sort()

        merged = []
        prev_start, prev_size = self.free_list[0]

        for curr_start, curr_size in self.free_list[1:]:
            if prev_start + prev_size == curr_start:
                prev_size += curr_size
            else:
                merged.append((prev_start, prev_size))
                prev_start, prev_size = curr_start, curr_size

        merged.append((prev_start, prev_size))
        self.free_list = merged


class MMU:
    def __init__(self, logger):
        self.logger = logger
        self.process_memory = {}

    def translate(self, address: int, pid: PID) -> int | None:
        if pid not in self.process_memory:
            return None
        mem = self.process_memory[pid]
        heap_start = 0x20000000
        heap_end = heap_start + mem["heap_size"]

        if mem["heap_size"] > 0 and heap_start <= address < heap_end:
            offset = address - heap_start
            return mem["heap_base"] + offset

        stack_top = 0xEFFFFFFF
        stack_bottom = stack_top - mem["stack_size"] + 1

        if stack_bottom <= address <= stack_top:
            offset = stack_top - address
            return mem["stack_base"] + (mem["stack_size"] - 1 - offset)

        return None


def exceeded_quantum(pcb: PCB) -> bool:
    if pcb.num_quantum_ticks >= RR_QUANTUM_TICKS:
        pcb.num_quantum_ticks = 0
        return True
    return False


def pop_min_priority(pcbs: list[PCB]) -> PCB:
    min_index = 0
    for i in range(1, len(pcbs)):
        if pcbs[i].priority < pcbs[min_index].priority or (pcbs[i].priority == pcbs[min_index].priority and pcbs[i].pid < pcbs[min_index].pid):
            min_index = i
    return pcbs.pop(min_index)


def pop_min_pid(pcbs: list[PCB]):
    lowest_pid_i = 0
    for i in range(1, len(pcbs)):
        if pcbs[i].pid < pcbs[lowest_pid_i].pid:
            lowest_pid_i = i
    return pcbs.pop(lowest_pid_i)
