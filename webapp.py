import streamlit as st
from collections import defaultdict
import pandas as pd
import altair as alt

# --- Helper Functions ---
def time_to_minutes(time_str):
    try:
        h, m, s = map(int, time_str.split(":"))
        return h * 60 + m + s / 60
    except (ValueError, IndexError): return 0.0

def calculate_efficiency(total_minutes, personal_shift_minutes):
    if personal_shift_minutes == 0: return 0.0
    return round((total_minutes / personal_shift_minutes) * 100, 2)

def calculate_headcount_recommendation(total_work_minutes, shift_minutes, target_efficiency):
    if shift_minutes == 0 or target_efficiency == 0: return 999
    effective_capacity_per_associate = shift_minutes * (target_efficiency / 100)
    if effective_capacity_per_associate == 0: return 999
    required_headcount = total_work_minutes / effective_capacity_per_associate
    return int(required_headcount) + (1 if required_headcount > int(required_headcount) else 0)

def assign_and_balance_workload(associates, work_volumes, task_times, shift_minutes, target_efficiency):
    # Set up each associate with their personal capacity based on OT
    for assoc in associates:
        overtime_pct = assoc.get('overtime_pct', 0)
        personal_shift_minutes = shift_minutes * (1 + overtime_pct / 100)
        personal_capacity = personal_shift_minutes * (target_efficiency / 100)
        assoc.update({
            "total_work": 0, "fulfillment_time": 0, "putaway_time": 0, "stock_request_time": 0, 
            "fulfillment_overage": 0, "personal_capacity": personal_capacity, "personal_shift_minutes": personal_shift_minutes
        })
        
    unassigned_work = {"putaway": work_volumes['num_putaway'], "stock_request": work_volumes['num_stock_requests'], "fulfillment_minutes": 0}
    wc_ownership = defaultdict(list)
    for i, assoc in enumerate(associates):
        for wc in assoc['workcenters']: wc_ownership[wc].append(i)

    for wc, items in work_volumes["replenishment_items"].items():
        if wc in wc_ownership:
            owners_indices = wc_ownership[wc]
            work_time_per_owner = (items * task_times["picking_time"]) / len(owners_indices)
            for index in owners_indices: associates[index]['fulfillment_time'] += work_time_per_owner
    
    for assoc in associates:
        assoc['total_work'] = assoc['fulfillment_time']
        if assoc["total_work"] > assoc['personal_capacity']:
            # FIX: Corrected quote for 'fulfillment_overage'
            assoc["fulfillment_overage"] = assoc["total_work"] - assoc['personal_capacity']
            unassigned_work["fulfillment_minutes"] += assoc["fulfillment_overage"]

    while unassigned_work['putaway'] > 0 or unassigned_work['stock_request'] > 0:
        eligible_associates = sorted(
            [a for a in associates if a["total_work"] < a['personal_capacity']],
            key=lambda a: a["total_work"]
        )
        if not eligible_associates: break

        task_assigned_this_pass = False
        for assignee in eligible_associates:
            for task_type in assignee['priorities']:
                if task_type == "putaway" and unassigned_work['putaway'] > 0:
                    assignee['putaway_time'] += task_times['putaway_time']
                    assignee["total_work"] += task_times['putaway_time']
                    unassigned_work['putaway'] -= 1
                    task_assigned_this_pass = True
                    break
                elif task_type == "stock_request" and unassigned_work['stock_request'] > 0:
                    assignee['stock_request_time'] += task_times['stock_request_time']
                    assignee["total_work"] += task_times['stock_request_time']
                    unassigned_work['stock_request'] -= 1
                    task_assigned_this_pass = True
                    break
            if task_assigned_this_pass: break
        if not task_assigned_this_pass: break
        
    return associates, unassigned_work

# --- NEW: Centralized Results Display Function (MOVED HERE) ---
def display_results(final_associates, unassigned_work, shift_minutes_base, target_efficiency_base):
    all_associates_balanced = True
    report_cols = st.columns(len(final_associates)) if final_associates else []
    for i, assoc in enumerate(final_associates):
        with report_cols[i]:
            efficiency = calculate_efficiency(assoc["total_work"], assoc['personal_shift_minutes'])
            delta = efficiency - target_efficiency_base
            st.subheader(assoc['name'])
            
            if abs(delta) <= 5.0:
                delta_color = "inverse" if delta < 0 else "normal"
            else:
                all_associates_balanced = False
                delta_color = "normal" if delta < 0 else "inverse"
            st.metric(label="Efficiency vs. Target", value=f"{efficiency:.1f}%", delta=f"{delta:.1f}% vs {target_efficiency_base}%", delta_color=delta_color)
            
            with st.container(border=True):
                overtime_pct = assoc.get('overtime_pct', 0)
                if overtime_pct > 0:
                    st.markdown(f"**Shift:** Standard + {overtime_pct}% OT")
                st.write(f"**Assigned WCs:** {assoc['workcenters'] or 'None'}")
                st.write(f"- Fulfillment: {assoc['fulfillment_time']:.1f} mins")
                st.write(f"- Putaway: {assoc['putaway_time']:.1f} mins")
                st.write(f"- Stock Request: {assoc['stock_request_time']:.1f} mins")
                st.markdown(f"**Total Work: {assoc['total_work']:.1f} / {assoc['personal_capacity']:.1f} mins**")
    
    st.divider()

    if final_associates:
        st.header("Visual Workload Summary")
        
        chart_data = {
            "Associate": [assoc['name'] for assoc in final_associates],
            "Total Work (mins)": [assoc['total_work'] for assoc in final_associates],
            "Target Capacity (mins)": [assoc['personal_capacity'] for assoc in final_associates]
        }
        df = pd.DataFrame(chart_data)
        
        bars = alt.Chart(df).mark_bar().encode(
            x=alt.X('Associate:N', sort=None, title="Associate"),
            y=alt.Y('Total Work (mins):Q', title="Minutes"),
            tooltip=['Associate', 'Total Work (mins)', 'Target Capacity (mins)']
        )
        
        line = alt.Chart(df).mark_line(color='red', strokeDash=[5,5], point=True).encode(
            x=alt.X('Associate:N', sort=None),
            y=alt.Y('Target Capacity (mins):Q')
        )
        
        chart = (bars + line).properties(
            title="Assigned Work vs. Target Capacity"
        ).interactive()
        
        st.altair_chart(chart, use_container_width=True)

    if any(val > 0 for val in unassigned_work.values()):
        st.subheader("Action Plan: Unassigned Work & Recommendations")
        if unassigned_work["fulfillment_minutes"] > 0:
            st.error("CRITICAL: Fulfillment work will be dropped due to over-assignment.")
            overloaded = [a for a in final_associates if a['fulfillment_overage'] > 0]
            for assoc in overloaded: st.write(f"  - **{assoc['name']}** is over capacity by **{assoc['fulfillment_overage']:.2f} minutes** from their fulfillment tasks alone.")
            underloaded = min((a for a in final_associates if not a['fulfillment_overage']), key=lambda x: x['total_work'], default=None)
            st.info("💡 **SUGGESTION:**")
            if underloaded: st.write(f"  Consider re-assigning a workcenter from **{overloaded[0]['name']}** to **{underloaded['name']}** and regenerate the plan.")
            else: st.write("  All associates are at/over capacity. Add more staff or reduce workload to meet targets.")


        if unassigned_work["putaway"] > 0 or unassigned_work["stock_request"] > 0:
            st.warning("The following secondary tasks will be carried over because no available associate had capacity or the correct priority:")
            if unassigned_work["putaway"] > 0: st.write(f"- Unassigned Putaway Transactions: **{unassigned_work['putaway']}**")
            if unassigned_work["stock_request"] > 0: st.write(f"- Unassigned Stock Requests: **{unassigned_work['stock_request']}**")
    elif not all_associates_balanced:
        st.error("**CRITICAL: The plan is unbalanced.** One or more associates are outside the allowable +/- 5% efficiency range.")
    else:
        st.success("✅ **Plan Complete!** All tasks have been assigned AND all associates are balanced within the target efficiency range.")


# --- Master List of Workcenters ---
MASTER_WORKCENTERS = [
    "ATL:COM:Wingbox Sub", "ATL:TECH:Tactical Prod", "ATL:TECH:Tactical AUR",
    "ATL:TECH:Battery Prod", "ATL:TECH:C2GSE", "ATL:TECH:3D Print Lab",
    "ATL:TECH:Prop Bal Lab", "ATL:TECH:Avi Sub Assy", "ATL:COM:Gearbox Sub",
    "ATL:COM:Fuse Assy","ATL:GPC:Flight Accpt",
    "ATL:COM:Payload", "ATL:COM:Final Assy", "ATL:TECH:NPI"
]

# --- Main App ---
st.set_page_config(layout="wide", page_title="Warehouse Staffing Planner")
st.title("Warehouse Staffing & Planning Tool")
with st.expander("📖 How to Use This Tool"):
    st.markdown("""
    This tool allows you to plan staffing for **Shift 1** and **Shift 2** separately. Any unassigned work from Shift 1 will automatically carry over to Shift 2's workload.

    1.  **Step 1: Configure Your Shift:** Enter standard times, a standard shift length, and target efficiency.
    2.  **Step 2: Enter Workload:** Define work volumes for putaway, stock requests, and item counts for each specific Workcenter.
    3.  **Headcount Analysis:** The tool recommends a headcount based on a *standard* workday.
    4.  **Step 3: Define Your Team:** Enable a slot for each associate. A green circle (🟢) will appear next to enabled slots. You can grant individual **Overtime %** to increase an associate's available work time. Assign Workcenters using the multi-select dropdown. Only Workcenters with items to fulfill will appear as options, and their current item count will be displayed next to their name.
    5.  **Generate Plan & Review:** The plan will distribute work based on each person's unique capacity. Efficiency is calculated against their personal scheduled hours (standard + OT).
    """)

# --- Session State Initialization for both shifts and carryover ---
if 'shift1_plan_generated' not in st.session_state:
    st.session_state.shift1_plan_generated = False
    st.session_state.shift1_final_associates = []
    st.session_state.shift1_unassigned_work = {}

if 'shift2_plan_generated' not in st.session_state:
    st.session_state.shift2_plan_generated = False
    st.session_state.shift2_final_associates = []
    st.session_state.shift2_unassigned_work = {}

if 'carryover_data' not in st.session_state:
    st.session_state.carryover_data = {
        "num_putaway": 0,
        "num_stock_requests": 0,
        "fulfillment_minutes": 0,
        "replenishment_items": {} # This will track items that couldn't be fulfilled per WC
    }

# --- Reusable function to render a single shift's UI and logic ---
def render_shift_inputs_and_logic(shift_id, initial_putaway_base=0, initial_stock_requests_base=0, initial_replenishment_items_base=None):
    if initial_replenishment_items_base is None:
        initial_replenishment_items_base = {}

    st.header(f"{shift_id.replace('shift', 'Shift ')} Details")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Time Standards")
        picking_time_str = st.text_input(f"Picking/Fulfillment Time (H:M:S)", "0:20:30", key=f"picking_time_str_{shift_id}")
        putaway_time_str = st.text_input(f"Putaway Time (H:M:S)", "0:16:00", key=f"putaway_time_str_{shift_id}")
        stock_req_time_str = st.text_input(f"Stock Request Time (H:M:S)", "0:17:00", key=f"stock_req_time_str_{shift_id}")
    with col2:
        st.subheader("Shift Configuration")
        shift_hours_str = st.text_input(f"Shift Working Hours (H:M:S)", "7:00:00", key=f"shift_hours_str_{shift_id}")
        target_efficiency = st.number_input(f"Target Operator Efficiency %", min_value=1, max_value=100, value=75, key=f"target_efficiency_{shift_id}")
    with col3:
        st.subheader("Daily Work Volume")
        
        # --- FIX: Combine user input and carryover for Putaway ---
        user_input_putaway_key = f"user_input_num_putaway_{shift_id}"
        if user_input_putaway_key not in st.session_state:
            st.session_state[user_input_putaway_key] = 0
        user_added_putaway = st.number_input(
            f"Number of Putaway Transactions (Manual Add)",
            min_value=0,
            value=st.session_state[user_input_putaway_key], # User's explicit input
            key=user_input_putaway_key,
            help=f"Enter additional putaway transactions for {shift_id.replace('shift', 'Shift ')}. Carryover from previous shift: {initial_putaway_base}"
        )
        num_putaway = user_added_putaway + initial_putaway_base # Total = User Input + Carryover

        # --- FIX: Combine user input and carryover for Stock Requests ---
        user_input_stock_key = f"user_input_num_stock_requests_{shift_id}"
        if user_input_stock_key not in st.session_state:
            st.session_state[user_input_stock_key] = 0
        user_added_stock_requests = st.number_input(
            f"Number of Stock Requests (Manual Add)",
            min_value=0,
            value=st.session_state[user_input_stock_key], # User's explicit input
            key=user_input_stock_key,
            help=f"Enter additional stock requests for {shift_id.replace('shift', 'Shift ')}. Carryover from previous shift: {initial_stock_requests_base}"
        )
        num_stock_requests = user_added_stock_requests + initial_stock_requests_base # Total = User Input + Carryover

    task_times = {
        "picking_time": time_to_minutes(picking_time_str), 
        "putaway_time": time_to_minutes(putaway_time_str), 
        "stock_request_time": time_to_minutes(stock_req_time_str)
    }
    shift_minutes = time_to_minutes(shift_hours_str)
    time_warning = False
    if shift_minutes == 0 and shift_hours_str not in ["0:0:0", "00:00:00"]:
        st.warning(f"[{shift_id}] Invalid 'Shift Working Hours' format. Please use H:M:S.", icon="⚠️")
        time_warning = True

    st.subheader("Fulfillment Details (Workcenters)")
    replenishment_items = {}
    st.markdown("Enter item counts for each workcenter below. Only workcenters with items > 0 will be included in the plan.")
    for wc_name in MASTER_WORKCENTERS:
        # --- FIX: Combine user input and carryover for Fulfillment Items ---
        user_input_item_wc_key = f"user_input_item_wc_{wc_name}_{shift_id}"
        if user_input_item_wc_key not in st.session_state:
            st.session_state[user_input_item_wc_key] = 0

        # Carryover for this specific WC (ensure it's an integer for display/addition)
        wc_carryover_items = int(round(initial_replenishment_items_base.get(wc_name, 0)))

        user_added_item_count = st.number_input(
            f"Items for **{wc_name}** (Manual Add)",
            min_value=0,
            value=st.session_state[user_input_item_wc_key], # User's explicit input
            key=user_input_item_wc_key,
            help=f"Enter additional items for {wc_name} for {shift_id.replace('shift', 'Shift ')}. Carryover from previous shift: {wc_carryover_items} items."
        )
        final_item_count = user_added_item_count + wc_carryover_items # Total = User Input + Carryover

        if final_item_count > 0:
            replenishment_items[wc_name] = final_item_count

    num_wcs = len(replenishment_items)

    total_work_minutes = sum(v * task_times["picking_time"] for v in replenishment_items.values()) + \
                         (num_putaway * task_times["putaway_time"]) + \
                         (num_stock_requests * task_times["stock_request_time"])
    recommended_headcount = calculate_headcount_recommendation(total_work_minutes, shift_minutes, target_efficiency) if shift_minutes > 0 and not time_warning else 0
    st.subheader("Headcount Analysis")
    st.info(f"Total workload is **{total_work_minutes:.2f} minutes**. Based on a standard workday, the recommended headcount is **{recommended_headcount}**.")

    st.subheader("Define Your Team & Generate Plan")

    ABSOLUTE_MAX_ASSOCIATES = 30 
    if f'num_associate_slots_{shift_id}' not in st.session_state:
        st.session_state[f'num_associate_slots_{shift_id}'] = max(1, recommended_headcount) 

    number_of_slots_to_display = st.number_input(
        f"Number of Associate Slots to Display for {shift_id.replace('shift', 'Shift ')}",
        min_value=1,
        max_value=ABSOLUTE_MAX_ASSOCIATES,
        value=st.session_state[f'num_associate_slots_{shift_id}'],
        key=f'num_associate_slots_{shift_id}',
        help=f"Adjust this to show more or fewer associate configuration slots for {shift_id.replace('shift', 'Shift ')}. Data for hidden slots is preserved."
    )

    associates_input = []
    st.write(f"**Enable and define each associate for {shift_id.replace('shift', 'Shift ')}'s plan.**")
    num_cols = 5 
    for i in range(0, number_of_slots_to_display, num_cols):
        cols = st.columns(num_cols)
        for j in range(num_cols):
            assoc_index = i + j
            if assoc_index < number_of_slots_to_display:
                with cols[j]:
                    is_currently_enabled = st.session_state.get(f'enabled_{assoc_index}_{shift_id}', False)
                    
                    status_icon = "🟢" if is_currently_enabled else "⚪"
                    expander_label = f"{status_icon} Associate Slot {assoc_index + 1}"
                    
                    with st.expander(expander_label, expanded=is_currently_enabled):
                        is_enabled = st.toggle("Enable this Associate", key=f"enabled_{assoc_index}_{shift_id}")
                        
                        if is_enabled:
                            name = st.text_input(f"Name", f"Associate {assoc_index + 1}", key=f"name_{assoc_index}_{shift_id}")
                            overtime_pct = st.number_input("Overtime %", min_value=0, max_value=200, value=0, step=5, key=f"ot_{assoc_index}_{shift_id}")
                            
                            # Only show WCs that have items (either manual or carryover)
                            available_wc_names_with_items = replenishment_items.keys()
                            multiselect_options_formatted = []
                            wc_name_to_formatted_name_map = {} 
                            for wc_name in available_wc_names_with_items:
                                item_count = replenishment_items[wc_name]
                                formatted_name = f"{wc_name} ({item_count} items)"
                                multiselect_options_formatted.append(formatted_name)
                                wc_name_to_formatted_name_map[wc_name] = formatted_name
                            
                            default_selected_raw_wcs = st.session_state.get(f"wcs_{assoc_index}_{shift_id}", [])
                            multiselect_default_formatted = [
                                wc_name_to_formatted_name_map[wc] 
                                for wc in default_selected_raw_wcs 
                                if wc in wc_name_to_formatted_name_map 
                            ]
                            
                            selected_formatted_wcs = st.multiselect(
                                f"Assigned Workcenters", 
                                options=multiselect_options_formatted, 
                                default=multiselect_default_formatted, 
                                key=f"wcs_{assoc_index}_formatted_{shift_id}" 
                            )
                            
                            wcs = [s.split(' (')[0] for s in selected_formatted_wcs]
                            st.session_state[f"wcs_{assoc_index}_{shift_id}"] = wcs 
                            
                            st.write("_Priority_")
                            tasks = ["putaway", "stock_request", "none"]
                            p1 = st.selectbox(f"P1", options=tasks, index=0, key=f"p1_{assoc_index}_{shift_id}")
                            p2_options = [t for t in tasks if t != p1] if p1 != 'none' else ['none']
                            p2_key = f"p2_{assoc_index}_{shift_id}"
                            current_p2_value = st.session_state.get(p2_key)
                            try:
                                p2_index = p2_options.index(current_p2_value)
                            except (ValueError, TypeError): p2_index = 0
                            p2 = st.selectbox(f"P2", options=p2_options, index=p2_index, key=p2_key)
                            priorities = [p for p in [p1, p2] if p != 'none']
                            associates_input.append({"name": name, "workcenters": wcs, "priorities": priorities, "overtime_pct": overtime_pct})

    actual_headcount = len(associates_input)
    st.info(f"**{actual_headcount}** associate(s) are enabled for {shift_id.replace('shift', 'Shift ')}'s plan.")

    can_generate = True
    if time_warning: can_generate = False
    
    # Check if there's any work in replenishment_items, either manual or carryover
    if actual_headcount > 0 and (num_putaway > 0 or num_stock_requests > 0 or len(replenishment_items) > 0):
        expected_wcs = set(replenishment_items.keys()) 
        assigned_wcs = {wc for assoc in associates_input for wc in assoc['workcenters']} 

        missing_wcs = expected_wcs - assigned_wcs
        if missing_wcs:
            st.error(f"[{shift_id}] **PLANNING HALTED:** Workcenter(s) **{sorted(list(missing_wcs))}** have work (items > 0) but are not assigned to any associate.")
            can_generate = False
        
        assigned_to_no_work = assigned_wcs - expected_wcs
        # Only show this warning if there are WCs with items OR if the assigned WCs are not in the master list
        if assigned_to_no_work and len(expected_wcs) > 0: # Only warn if some WCs actually have work defined
            st.warning(f"[{shift_id}] **WARNING:** Associate(s) are assigned to Workcenter(s) **{sorted(list(assigned_to_no_work))}** which currently have 0 items. These WCs will contribute no work to the plan.")

    elif actual_headcount == 0 and total_work_minutes > 0:
        st.warning(f"[{shift_id}] There is work to be done but no associates are enabled. Please enable associates in Step 3.")
        can_generate = False

    return {
        "associates_input": associates_input,
        "work_volumes": {
            "num_putaway": num_putaway,
            "num_stock_requests": num_stock_requests,
            "replenishment_items": replenishment_items
        },
        "task_times": task_times,
        "shift_minutes": shift_minutes,
        "target_efficiency": target_efficiency,
        "can_generate": can_generate,
        "total_work_minutes": total_work_minutes
    }

# --- Tabbed Interface ---
tab1, tab2 = st.tabs(["Shift 1 Planning", "Shift 2 Planning (with Carryover)"])

with tab1:
    shift1_data = render_shift_inputs_and_logic("shift1")
    
    if st.button("Generate Shift 1 Plan", key="generate_shift1_plan", disabled=not shift1_data["can_generate"]):
        final_associates, unassigned_work = assign_and_balance_workload(
            shift1_data["associates_input"],
            shift1_data["work_volumes"],
            shift1_data["task_times"],
            shift1_data["shift_minutes"],
            shift1_data["target_efficiency"]
        )
        st.session_state.shift1_final_associates = final_associates
        st.session_state.shift1_unassigned_work = unassigned_work
        st.session_state.shift1_plan_generated = True

        # Capture carryover for Shift 2
        st.session_state.carryover_data["num_putaway"] = unassigned_work["putaway"]
        st.session_state.carryover_data["num_stock_requests"] = unassigned_work["stock_request"]
        
        # Reset replenishment items for carryover
        st.session_state.carryover_data["replenishment_items"] = {}
        
        # Calculate unfulfilled items from fulfillment_minutes proportionally
        if shift1_data["task_times"]["picking_time"] > 0:
            unfulfilled_fulfillment_items_total = unassigned_work["fulfillment_minutes"] / shift1_data["task_times"]["picking_time"]
            total_items_in_shift1_original = sum(shift1_data["work_volumes"]["replenishment_items"].values())

            if total_items_in_shift1_original > 0:
                for wc, original_items_in_wc in shift1_data["work_volumes"]["replenishment_items"].items():
                    proportion = original_items_in_wc / total_items_in_shift1_original
                    carryover_wc_items = unfulfilled_fulfillment_items_total * proportion
                    if carryover_wc_items > 0.01: # Avoid carrying over tiny fractions
                        st.session_state.carryover_data["replenishment_items"][wc] = \
                            st.session_state.carryover_data["replenishment_items"].get(wc, 0) + carryover_wc_items
            elif unfulfilled_fulfillment_items_total > 0:
                 # If no original items but still unfulfilled minutes, might be an edge case or error,
                 # but we can't distribute it meaningfully without original WC context.
                 # For now, this case implies the "fulfillment minutes" are from no specific WCs or were distributed differently.
                 # Best to just warn/log if this occurs.
                 pass

        st.toast(f"Shift 1 plan generated! Carryover for Shift 2 calculated.", icon="✅")

    if st.session_state.shift1_plan_generated:
        st.divider()
        st.subheader("Shift 1 Final Tasking Plan")
        display_results(st.session_state.shift1_final_associates, st.session_state.shift1_unassigned_work,
                        shift1_data["shift_minutes"], shift1_data["target_efficiency"])

with tab2:
    st.markdown("---")
    st.subheader("Shift 2 Carryover from Shift 1")
    if st.session_state.shift1_plan_generated:
        carry = st.session_state.carryover_data
        has_carryover = False
        if carry["num_putaway"] > 0: has_carryover = True
        if carry["num_stock_requests"] > 0: has_carryover = True
        if any(val > 0 for val in carry["replenishment_items"].values()): has_carryover = True

        if has_carryover:
            st.info(f"**Carryover from Shift 1:**")
            if carry["num_putaway"] > 0: st.write(f"- Putaway Transactions: **{carry['num_putaway']}**")
            if carry["num_stock_requests"] > 0: st.write(f"- Stock Requests: **{carry['num_stock_requests']}**")
            if any(val > 0 for val in carry["replenishment_items"].values()):
                st.write(f"- Fulfillment Items for WCs: {', '.join([f'{wc}: {int(round(items))} items' for wc, items in carry['replenishment_items'].items()])}")
        else:
            st.success("No unassigned work carried over from Shift 1.")
    else:
        st.warning("Please generate Shift 1 plan first to calculate carryover data.")
    
    st.markdown("---")

    # Pass carryover data to Shift 2's inputs
    shift2_data = render_shift_inputs_and_logic(
        "shift2",
        initial_putaway_base=st.session_state.carryover_data["num_putaway"],
        initial_stock_requests_base=st.session_state.carryover_data["num_stock_requests"],
        initial_replenishment_items_base=st.session_state.carryover_data["replenishment_items"]
    )

    if st.button("Generate Shift 2 Plan", key="generate_shift2_plan", disabled=not shift2_data["can_generate"]):
        final_associates, unassigned_work = assign_and_balance_workload(
            shift2_data["associates_input"],
            shift2_data["work_volumes"],
            shift2_data["task_times"],
            shift2_data["shift_minutes"],
            shift2_data["target_efficiency"]
        )
        st.session_state.shift2_final_associates = final_associates
        st.session_state.shift2_unassigned_work = unassigned_work
        st.session_state.shift2_plan_generated = True
        st.toast(f"Shift 2 plan generated!", icon="✅")

    if st.session_state.shift2_plan_generated:
        st.divider()
        st.subheader("Shift 2 Final Tasking Plan")
        display_results(st.session_state.shift2_final_associates, st.session_state.shift2_unassigned_work,
                        shift2_data["shift_minutes"], shift2_data["target_efficiency"])