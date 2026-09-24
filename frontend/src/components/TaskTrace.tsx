import type { TaskResult } from "../lib/api";

/**
 * Jejak eksekusi planner untuk satu balasan: menampilkan tiap task,
 * hasilnya, dan apakah lolos evaluasi reflection loop (§14 master prompt) --
 * supaya pemakai (developer-nya sendiri) bisa melihat "cara berpikir"
 * Thinker, bukan cuma jawaban akhirnya.
 */
export function TaskTrace({ tasks }: { tasks: TaskResult[] }) {
  return (
    <details className="mt-3 border border-(--color-hairline) px-3 py-2 text-sm open:pb-3">
      <summary className="cursor-pointer select-none text-(--color-amber)">planner &middot; {tasks.length} task</summary>
      <ol className="mt-2 flex flex-col gap-2">
        {tasks.map((task, index) => (
          <li key={index} className="border-l-2 border-(--color-hairline) pl-3">
            <div className="flex items-baseline gap-2">
              <span className={task.passed_evaluation ? "text-(--color-signal)" : "text-(--color-danger)"}>{task.passed_evaluation ? "selesai" : "belum tuntas"}</span>
              <span className="text-(--color-paper)">{task.description}</span>
              {task.attempts > 1 && <span className="text-(--color-muted)">({task.attempts}x percobaan)</span>}
            </div>
            <p className="mt-1 text-(--color-muted)">{task.result}</p>
          </li>
        ))}
      </ol>
    </details>
  );
}
