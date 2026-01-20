import streamlit as st
from collections import defaultdict

# --- Helper Functions (unchanged) ---
def time_to_minutes(time_str):
    try:
        h, m, s = map(int, time_str.split(":"))
        return h * 60 + m + s / 60
    except (ValueError, IndexError): return 0.0

def calculate_efficiency(total_minutes, shift_minutes):
    if shift_minutes == 0: return 0.0
    return round((total_minutes / shift_minutes) * 100, 2)

def calculate_headcount_recommendation(total_work_minutes, shift_minutes, target_efficiency):
    if shift_minutes == 0 or target_efficiency == 0: return 999
    effective_capacity_per_associate = shift_minutes * (target_efficiency / 100)
    if effective_capacity_per_associate == 0: return 999
    required_headcount = total_work_minutes / effective_capacity_per_associate
    return int(required_headcount) + (1 if required_headcount > int(required_headcount) else 0)

def assign_and_balance_workload(associates, work_volumes, task_times, shift_minutes, target_efficiency):
    capacity_limit = shift_minutes * (target_efficiency / 100)
    for assoc in associates:
        assoc.update({"total_work": 0, "fulfillment_time": 0, "putaway_time": 0, "stock_request_time": 0, "fulfillment_overage": 0})
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
        if assoc["total_work"] > capacity_limit:
            assoc["fulfillment_overage"] = assoc["total_work"] - capacity_limit
            unassigned_work["fulfillment_minutes"] += assoc["fulfillment_overage"]
    while unassigned_work['putaway'] > 0 or unassigned_work['stock_request'] > 0:
        eligible_associates = [a for a in associates if a["total_work"] < capacity_limit]
        if not eligible_associates: break
        assignee = min(eligible_associates, key=lambda a: a["total_work"])
        task_assigned_this_round = False
        for task_type in assignee['priorities']:
            if task_type == "putaway" and unassigned_work['putaway'] > 0:
                assignee['putaway_time'] += task_times['putaway_time']
                assignee["total_work"] += task_times['putaway_time']
                unassigned_work['putaway'] -= 1
                task_assigned_this_round = True
                break
            elif task_type == "stock_request" and unassigned_work['stock_request'] > 0:
                assignee['stock_request_time'] += task_times['stock_request_time']
                assignee["total_work"] += task_times['stock_request_time']
                unassigned_work['stock_request'] -= 1
                task_assigned_this_round = True
                break
        if not task_assigned_this_round: break
    return associates, unassigned_work

# --- Main App ---
st.set_page_config(layout="wide", page_title="Warehouse Staffing Planner")
st.title("Warehouse Staffing & Planning Tool")

with st.expander("📖 How to Use This Tool"):
    st.markdown("""
    1.  **Step 1: Configure Your Shift:** Enter standard times, shift length, target efficiency, and total work volume.
    2.  **Step 2: Enter Fulfillment:** Define workcenters and item counts. If multiple associates share a workcenter, its work will be split equally.
    3.  **Headcount Analysis:** The tool recommends the ideal headcount.
    4.  **Step 3: Define Your Team:** Enter your actual headcount. For each associate, define their owned workcenters and personal priority for secondary tasks. Use **"none"** to exclude them from a task type.
    5.  **Generate Plan:** The tool performs safety checks (like ensuring all workcenters are assigned). Click the button to generate the plan.
    6.  **Review the Plan:** The report shows each person's workload and their efficiency relative to your target. **Green** deltas are within the allowable +/- 5% range. **Red** deltas are out of range and require attention.
    """)

if 'plan_generated' not in st.session_state:
    st.session_state.plan_generated = False
    st.session_state.final_associates = []
    st.session_state.unassigned_work = {}

st.header("Step 1: Enter Shift Details & Workload")
col1, col2, col3 = st.columns(3)
with col1:
    st.subheader("Time Standards")
    picking_time_str = st.text_input("Picking/Fulfillment Time", "0:17:00")
    putaway_time_str = st.text_input("Putaway Time", "0:16:00")
    stock_req_time_str = st.text_input("Stock Request Time", "0:20:30")
with col2:
    st.subheader("Shift Configuration")
    shift_hours_str = st.text_input("Shift Working Hours", "8:00:00")
    target_efficiency = st.number_input("Target Operator Efficiency %", min_value=1, max_value=100, value=85)
with col3:
    st.subheader("Daily Work Volume")
    num_putaway = st.number_input("Number of Putaway Transactions", min_value=0, value=20)
    num_stock_requests = st.number_input("Number of Stock Requests", min_value=0, value=15)

st.header("Step 2: Enter Fulfillment Details")
num_wcs = st.number_input("Number of Workcenters for Fulfillment", min_value=0, value=3)
replenishment_items = {i+1: st.number_input(f"Items for WC {i+1}", min_value=0, value=50, key=f"wc_{i+1}") for i in range(num_wcs)}

task_times = {"picking_time": time_to_minutes(picking_time_str), "putaway_time": time_to_minutes(putaway_time_str), "stock_request_time": time_to_minutes(stock_req_time_str)}
shift_minutes = time_to_minutes(shift_hours_str)
total_work_minutes = sum(v * task_times["picking_time"] for v in replenishment_items.values()) + (num_putaway * task_times["putaway_time"]) + (num_stock_requests * task_times["stock_request_time"])
recommended_headcount = calculate_headcount_recommendation(total_work_minutes, shift_minutes, target_efficiency) if shift_minutes > 0 else 0

st.subheader("Headcount Analysis")
st.info(f"Total workload is **{total_work_minutes:.2f} minutes**. At {target_efficiency}% efficiency, the recommended headcount is **{recommended_headcount}**.")

st.header("Step 3: Define Your Team & Generate Plan")
actual_headcount = st.number_input("Enter your ACTUAL available headcount", min_value=1, value=recommended_headcount)
associates_input = []
if actual_headcount > 0:
    st.write("**Define associate names, their assigned workcenters (e.g., '1, 3'), and their personal task priorities.**")
    assoc_cols = st.columns(actual_headcount)
    for i in range(actual_headcount):
        with assoc_cols[i]:
            name = st.text_input(f"**Associate {i+1} Name**", f"Associate {i+1}", key=f"name_{i}")
            wcs_str = st.text_input(f"Workcenters for {name}", "none", key=f"wcs_{i}")
            wcs = [int(x.strip()) for x in wcs_str.split(',') if x.strip().isdigit()] if wcs_str not in ["", "none"] else []
            st.write("_Secondary Task Priority_")
            tasks = ["putaway", "stock_request", "none"]
            p1 = st.selectbox(f"P1 for {name}", options=tasks, index=0, key=f"p1_{i}")
            p2_options = [t for t in tasks if t != p1] if p1 != 'none' else ['none']
            p2 = st.selectbox(f"P2 for {name}", options=p2_options, index=0, key=f"p2_{i}")
            priorities = [p for p in [p1, p2] if p != 'none']
            associates_input.append({"name": name, "workcenters": wcs, "priorities": priorities})

can_generate = True
if num_wcs > 0:
    expected_wcs = set(replenishment_items.keys())
    assigned_wcs = {wc for assoc in associates_input for wc in assoc['workcenters']}
    missing_wcs = expected_wcs - assigned_wcs
    if missing_wcs:
        st.error(f"**PLANNING HALTED:** Workcenter(s) **{list(missing_wcs)}** have items but are not assigned to any associate. Please assign them before generating a plan.")
        can_generate = False

if st.button("Generate Staffing Plan", disabled=not can_generate):
    work_volumes = {"num_putaway": num_putaway, "num_stock_requests": num_stock_requests, "replenishment_items": replenishment_items}
    final_associates, unassigned_work = assign_and_balance_workload(associates_input, work_volumes, task_times, shift_minutes, target_efficiency)
    st.session_state.final_associates = final_associates
    st.session_state.unassigned_work = unassigned_work
    st.session_state.plan_generated = True

if st.session_state.plan_generated:
    st.header("Final Tasking Plan")
    all_associates_balanced = True
    report_cols = st.columns(len(st.session_state.final_associates)) if st.session_state.final_associates else []

    for i, assoc in enumerate(st.session_state.final_associates):
        with report_cols[i]:
            efficiency = calculate_efficiency(assoc["total_work"], shift_minutes)
            delta = efficiency - target_efficiency
            st.subheader(assoc['name'])
            
            # --- [NEW] Precise Green/Red Color Logic ---
            if abs(delta) <= 5.0:
                # In range! Force GREEN.
                delta_color = "inverse" if delta < 0 else "normal"
            else:
                # Out of range! Force RED.
                all_associates_balanced = False
                delta_color = "normal" if delta < 0 else "inverse"
            
            st.metric(label="Efficiency vs. Target", value=f"{efficiency:.1f}%", delta=f"{delta:.1f}% vs {target_efficiency}%", delta_color=delta_color)

            with st.container(border=True):
                st.write(f"**Assigned WCs:** {assoc['workcenters'] or 'None'}")
                st.write(f"- Fulfillment: {assoc['fulfillment_time']:.1f} mins")
                st.write(f"- Putaway: {assoc['putaway_time']:.1f} mins")
                st.write(f"- Stock Request: {assoc['stock_request_time']:.1f} mins")
                st.markdown(f"**Total Work: {assoc['total_work']:.1f} mins**")
    
    st.divider()
    unassigned = st.session_state.unassigned_work
    
    if any(unassigned.values()):
        st.subheader("Action Plan: Unassigned Work & Recommendations")
        # ... (error and recommendation logic remains the same)
        if unassigned["fulfillment_minutes"] > 0:
            st.error("CRITICAL: Fulfillment work will be dropped due to over-assignment.")
            overloaded = [a for a in st.session_state.final_associates if a['fulfillment_overage'] > 0]
            for assoc in overloaded: st.write(f"  - **{assoc['name']}** is over capacity by **{assoc['fulfillment_overage']:.2f} minutes** from their fulfillment tasks alone.")
            underloaded = min((a for a in st.session_state.final_associates if not a['fulfillment_overage']), key=lambda x: x['total_work'], default=None)
            st.info("💡 **SUGGESTION:**")
            if underloaded: st.write(f"  Consider re-assigning a workcenter from **{overloaded[0]['name']}** to **{underloaded['name']}** and regenerate the plan.")
            else: st.write("  All associates are at/over capacity. Add more staff or reduce workload to meet targets.")
        
        if unassigned["putaway"] > 0 or unassigned["stock_request"] > 0:
            st.warning("The following secondary tasks will be carried over based on individual priorities:")
            if unassigned["putaway"] > 0: st.write(f"- Unassigned Putaway Transactions: **{unassigned['putaway']}**")
            if unassigned["stock_request"] > 0: st.write(f"- Unassigned Stock Requests: **{unassigned['stock_request']}**")
            
    elif not all_associates_balanced:
        st.error("**CRITICAL: The plan is unbalanced.** One or more associates are outside the allowable +/- 5% efficiency range. Review the individual metrics above.")
    else:
        st.success("✅ **Plan Complete!** All tasks have been assigned AND all associates are balanced within the target efficiency range.")