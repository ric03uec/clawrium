import { render, screen, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelComboBox } from "./model-combobox";
import type { ModelInfo } from "@/lib/types";

const models: ModelInfo[] = [
  {
    id: "gpt-4o",
    name: "GPT-4o",
    lab: "OpenAI",
    context_window: 128000,
    tags: ["multimodal", "tool-use"],
  },
  {
    id: "gpt-4o-mini",
    name: "GPT-4o mini",
    lab: "OpenAI",
    context_window: 128000,
    tags: ["multimodal"],
  },
  {
    id: "claude-sonnet-4-5",
    name: "Claude Sonnet 4.5",
    lab: "Anthropic",
    context_window: 200000,
    tags: ["reasoning"],
  },
];

let user: UserEvent;

beforeEach(() => {
  user = userEvent.setup();
});

describe("ModelComboBox — rendering & display", () => {
  it("renders all options when opened", async () => {
    render(<ModelComboBox value="" onChange={() => {}} options={models} />);
    await user.click(screen.getByRole("combobox"));
    const listbox = screen.getByRole("listbox");
    expect(within(listbox).getByText("gpt-4o")).toBeInTheDocument();
    expect(within(listbox).getByText("gpt-4o-mini")).toBeInTheDocument();
    expect(within(listbox).getByText("claude-sonnet-4-5")).toBeInTheDocument();
  });

  it("displays the controlled value when closed", () => {
    // B1: closed-state displayValue path — selected?.id branch
    render(
      <ModelComboBox
        value="claude-sonnet-4-5"
        onChange={() => {}}
        options={models}
      />,
    );
    const input = screen.getByRole<HTMLInputElement>("combobox");
    expect(input.value).toBe("claude-sonnet-4-5");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("clears the input for fresh search when opening with a selected value", async () => {
    // B1: open path replaces selected display with empty query
    render(
      <ModelComboBox
        value="claude-sonnet-4-5"
        onChange={() => {}}
        options={models}
      />,
    );
    const input = screen.getByRole<HTMLInputElement>("combobox");
    await user.click(input);
    expect(input.value).toBe("");
  });
});

describe("ModelComboBox — filtering", () => {
  it("filters by lab name", async () => {
    render(<ModelComboBox value="" onChange={() => {}} options={models} />);
    const input = screen.getByRole("combobox");
    await user.click(input);
    await user.type(input, "anthropic");
    const listbox = screen.getByRole("listbox");
    expect(within(listbox).getByText("claude-sonnet-4-5")).toBeInTheDocument();
    // W2: assert both other models are gone
    expect(within(listbox).queryByText("gpt-4o")).not.toBeInTheDocument();
    expect(within(listbox).queryByText("gpt-4o-mini")).not.toBeInTheDocument();
  });

  it("filters by tag", async () => {
    render(<ModelComboBox value="" onChange={() => {}} options={models} />);
    const input = screen.getByRole("combobox");
    await user.click(input);
    await user.type(input, "reasoning");
    const listbox = screen.getByRole("listbox");
    expect(within(listbox).getByText("claude-sonnet-4-5")).toBeInTheDocument();
    expect(within(listbox).queryByText("gpt-4o")).not.toBeInTheDocument();
  });

  it("filters by display name", async () => {
    // W1: covers m.name branch in matchModel
    render(<ModelComboBox value="" onChange={() => {}} options={models} />);
    const input = screen.getByRole("combobox");
    await user.click(input);
    await user.type(input, "GPT-4o mini");
    const listbox = screen.getByRole("listbox");
    expect(within(listbox).getByText("gpt-4o-mini")).toBeInTheDocument();
    expect(within(listbox).queryByText("claude-sonnet-4-5")).not.toBeInTheDocument();
  });

  it("shows empty-state when no models match", async () => {
    render(<ModelComboBox value="" onChange={() => {}} options={models} />);
    const input = screen.getByRole("combobox");
    await user.click(input);
    await user.type(input, "nonexistent-xyz");
    expect(
      within(screen.getByRole("listbox")).getByText("No models match"),
    ).toBeInTheDocument();
  });
});

describe("ModelComboBox — grouping", () => {
  it("groups by lab and renders lab headings", async () => {
    render(
      <ModelComboBox
        value=""
        onChange={() => {}}
        options={models}
        groupByLab
      />,
    );
    await user.click(screen.getByRole("combobox"));
    const listbox = screen.getByRole("listbox");
    expect(within(listbox).getByText("OpenAI")).toBeInTheDocument();
    expect(within(listbox).getByText("Anthropic")).toBeInTheDocument();
  });
});

describe("ModelComboBox — selection", () => {
  it("fires onChange with the model id when an option is clicked", async () => {
    const onChange = vi.fn();
    render(<ModelComboBox value="" onChange={onChange} options={models} />);
    await user.click(screen.getByRole("combobox"));
    // mouseDown is the production handler; fire it directly via pointer.
    await user.pointer({
      keys: "[MouseLeft]",
      target: screen.getByText("claude-sonnet-4-5"),
    });
    expect(onChange).toHaveBeenCalledWith("claude-sonnet-4-5");
  });

  it("closes the listbox and resets the input after selection", async () => {
    // W3: post-selection state
    function Harness() {
      const [v, setV] = require("react").useState("");
      return (
        <ModelComboBox value={v as string} onChange={setV} options={models} />
      );
    }
    render(<Harness />);
    await user.click(screen.getByRole("combobox"));
    await user.pointer({
      keys: "[MouseLeft]",
      target: screen.getByText("gpt-4o-mini"),
    });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByRole<HTMLInputElement>("combobox").value).toBe(
      "gpt-4o-mini",
    );
  });
});

describe("ModelComboBox — keyboard navigation", () => {
  it("ArrowDown + Enter selects the next option (ungrouped)", async () => {
    const onChange = vi.fn();
    render(
      <ModelComboBox
        value=""
        onChange={onChange}
        options={models}
        groupByLab={false}
      />,
    );
    await user.click(screen.getByRole("combobox"));
    await user.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("gpt-4o-mini");
  });

  it("ArrowUp clamps to the first option (ungrouped)", async () => {
    // B3: ArrowUp boundary + Math.max clamp
    const onChange = vi.fn();
    render(
      <ModelComboBox
        value=""
        onChange={onChange}
        options={models}
        groupByLab={false}
      />,
    );
    await user.click(screen.getByRole("combobox"));
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowUp}{ArrowUp}{ArrowUp}{Enter}");
    expect(onChange).toHaveBeenCalledWith("gpt-4o");
  });

  it("ArrowDown navigates across lab groups", async () => {
    // W7: cross-group runningIdx accumulation
    const onChange = vi.fn();
    render(
      <ModelComboBox
        value=""
        onChange={onChange}
        options={models}
        groupByLab
      />,
    );
    await user.click(screen.getByRole("combobox"));
    // visible order grouped & sorted by lab: Anthropic[claude-sonnet-4-5], OpenAI[gpt-4o, gpt-4o-mini]
    // start at idx 0 (claude). ArrowDown → 1 (gpt-4o). Enter selects.
    await user.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("gpt-4o");
  });

  it("Escape closes the listbox", async () => {
    // B3: Escape handler
    render(<ModelComboBox value="" onChange={() => {}} options={models} />);
    await user.click(screen.getByRole("combobox"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

describe("ModelComboBox — disabled", () => {
  it("disables the input and suppresses the dropdown", async () => {
    // B4
    render(
      <ModelComboBox
        value=""
        onChange={() => {}}
        options={models}
        disabled
      />,
    );
    const input = screen.getByRole<HTMLInputElement>("combobox");
    expect(input).toBeDisabled();
    // user.click is a no-op on disabled inputs, so trigger focus manually.
    input.focus();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

describe("ModelComboBox — click outside", () => {
  it("closes the listbox when mousedown lands outside", async () => {
    // B5
    render(
      <div>
        <ModelComboBox value="" onChange={() => {}} options={models} />
        <button type="button" data-testid="outside">
          outside
        </button>
      </div>,
    );
    await user.click(screen.getByRole("combobox"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await user.pointer({
      keys: "[MouseLeft]",
      target: screen.getByTestId("outside"),
    });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

describe("ModelComboBox — accessibility", () => {
  it("toggles aria-expanded and wires aria-controls to the listbox id", async () => {
    // W4 + W5
    render(
      <ModelComboBox
        value=""
        onChange={() => {}}
        options={models}
        inputId="model-field"
      />,
    );
    const input = screen.getByRole("combobox");
    expect(input).toHaveAttribute("id", "model-field");
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input).toHaveAttribute("aria-controls", "model-field-listbox");
    await user.click(input);
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("listbox")).toHaveAttribute(
      "id",
      "model-field-listbox",
    );
    await user.keyboard("{Escape}");
    expect(input).toHaveAttribute("aria-expanded", "false");
  });

  it("marks the selected option with aria-selected=true", async () => {
    // W4
    render(
      <ModelComboBox
        value="claude-sonnet-4-5"
        onChange={() => {}}
        options={models}
      />,
    );
    await user.click(screen.getByRole("combobox"));
    const selected = screen
      .getAllByRole("option")
      .find((el) => el.getAttribute("aria-selected") === "true");
    expect(selected).toBeDefined();
    expect(selected).toHaveTextContent("claude-sonnet-4-5");
  });
});

describe("ModelComboBox — list capping", () => {
  it("caps visible rows and shows a refine-search hint", async () => {
    const many: ModelInfo[] = Array.from({ length: 200 }, (_, i) => ({
      id: `m-${i}`,
      name: `Model ${i}`,
      lab: "Lab",
      context_window: 0,
      tags: [],
    }));
    render(
      <ModelComboBox
        value=""
        onChange={() => {}}
        options={many}
        maxVisible={50}
        groupByLab={false}
      />,
    );
    await user.click(screen.getByRole("combobox"));
    const listbox = screen.getByRole("listbox");
    expect(within(listbox).getByText("m-49")).toBeInTheDocument();
    expect(within(listbox).queryByText("m-50")).not.toBeInTheDocument();
    expect(within(listbox).getByText(/Showing 50 of 200/i)).toBeInTheDocument();
  });
});
