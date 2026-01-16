import streamlit as st

# --- Helper Functions ---
def time_to_minutes(time_str):
    try:
        h, m, s = map(int, time_str.split(":"))
        return h * 60 + m + s / 60
    except (ValueError, IndexError):
        return 0.0

def calculate_efficiency(total_minutes, shift_minutes):
    if shift_minutes == 0: return 0.0
    return round((total_minutes / shift_minutes) * 100, 2)

def calculate_headcount_recommendation(total_work_minutes, shift_minutes, target_efficiency):
    if shift_minutes == 0 or target_efficiency == 0: return 999
    effective_capacity_per_associate = shift_minutes * (target_efficiency / 100)
    if effective_capacity_per_associate == 0: return 999
    required_headcount = total_work_minutes / effective_capacity_per_associate
    return int(required_headcount) + (1 if required_headcount > int(required_headcount) else 0)

# --- [UPGRADED] This function now strictly follows the priorities list ---
def assign_and_balance_workload(associates, work_volumes, task_times, priorities, shift_minutes, target_efficiency):
    capacity_limit = shift_minutes * (target_efficiency / 100)
    for assoc in associates:
        assoc.update({"total_work": 0, "fulfillment_time": 0, "putaway_time": 0, "stock_request_time": 0, "fulfillment_overage": 0})
    
    unassigned_work = {"putaway": work_volumes['num_putaway'], "stock_request": work_volumes['num_stock_requests'], "fulfillment_minutes": 0}
    
    # This loop is now the core of the decision making. It assigns work in the exact order provided.
    for task_type in priorities:
        if task_type == "fulfillment":
            for assoc in associates:
                fulfillment_work = sum(work_volumes["replenishment_items"].get(wc, 0) * task_times["picking_time"] for wc in assoc["workcenters"])
                assoc["fulfillment_time"] = fulfillment_work
                assoc["total_work"] += fulfillment_work
                if assoc["total_work"] > capacity_limit:
                    overage = assoc["total_work"] - capacity_limit
                    assoc["fulfillment_overage"] = overage
                    unassigned_work["fulfillment_minutes"] += overage
        elif task_type == "putaway":
            for _ in range(work_volumes['num_putaway']):
                eligible_associates = [a for a in associates if a["total_work"] < capacity_limit]
                if not eligible_associates: break # Stop assigning if everyone is full
                assignee = min(eligible_associates, key=lambda a: a["total_work"])
                assignee['putaway_time'] += task_times['putaway_time']
                assignee["total_work"] += task_times['putaway_time']
                unassigned_work['putaway'] -= 1
        elif task_type == "stock_request":
            for _ in range(work_volumes['num_stock_requests']):
                eligible_associates = [a for a in associates if a["total_work"] < capacity_limit]
                if not eligible_associates: break # Stop assigning if everyone is full
                assignee = min(eligible_associates, key=lambda a: a["total_work"])
                assignee['stock_request_time'] += task_times['stock_request_time']
                assignee["total_work"] += task_times['stock_request_time']
                unassigned_work['stock_request'] -= 1
    return associates, unassigned_work

# --- UI Functions ---
def get_work_prioritization_ui():
    st.warning("Headcount is less than recommended. Please rank tasks to determine carryover.")
    tasks = ["fulfillment", "putaway", "stock_request"]
    
    # Use columns for a cleaner layout
    c1, c2, c3 = st.columns(3)
    with c1:
        p1 = st.selectbox("Priority 1 (Highest)", options=tasks, index=0)
    
    p2_options = [t for t in tasks if t != p1]
    with c2:
        p2 = st.selectbox("Priority 2", options=p2_options, index=0)
        
    p3_options = [t for t in p2_options if t != p2]
    with c3:
        p3 = st.selectbox("Priority 3 (Lowest)", options=p3_options, index=0)
    
    return [p1, p2, p3]

# --- Main App ---
st.set_page_config(layout="wide", page_title="Warehouse Staffing Planner")
st.title("Warehouse Staffing & Planning Tool")

# Initialize session state variables
if 'plan_generated' not in st.session_state:
    st.session_state.plan_generated = False
    st.session_state.final_associates = []
    st.session_state.unassigned_work = {}

# --- INPUTS ---
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

# --- Calculations ---
task_times = {"picking_time": time_to_minutes(picking_time_str), "putaway_time": time_to_minutes(putaway_time_str), "stock_request_time": time_to_minutes(stock_req_time_str)}
shift_minutes = time_to_minutes(shift_hours_str)
total_work_minutes = sum(v * task_times["picking_time"] for v in replenishment_items.values()) + (num_putaway * task_times["putaway_time"]) + (num_stock_requests * task_times["stock_request_time"])
recommended_headcount = calculate_headcount_recommendation(total_work_minutes, shift_minutes, target_efficiency) if shift_minutes > 0 else 0

st.subheader("Headcount Analysis")
st.info(f"Total workload is **{total_work_minutes:.2f} minutes**. At {target_efficiency}% efficiency, the recommended headcount is **{recommended_headcount}**.")

# --- Prioritization and Team Definition ---
st.header("Step 3: Define Your Team & Generate Plan")
actual_headcount = st.number_input("Enter your ACTUAL available headcount", min_value=1, value=recommended_headcount, key='actual_headcount')

priorities = ["fulfillment", "putaway", "stock_request"]
if actual_headcount < recommended_headcount:
    with st.container(border=True):
        priorities = get_work_prioritization_ui()

st.write("**Define associate names and their assigned workcenters (e.g., '1, 3').**")
associates_input = []
if actual_headcount > 0:
    assoc_cols = st.columns(actual_headcount)
    for i in range(actual_headcount):
        with assoc_cols[i]:
            name = st.text_input(f"Associate {i+1} Name", f"Associate {i+1}", key=f"name_{i}")
            wcs_str = st.text_input(f"Workcenters for {name}", "none", key=f"wcs_{i}")
            wcs = [int(x.strip()) for x in wcs_str.split(',') if x.strip().isdigit()] if wcs_str not in ["", "none"] else []
            associates_input.append({"name": name, "workcenters": wcs})

# --- Generate Plan Button ---
if st.button("Generate Staffing Plan"):
    work_volumes = {"num_putaway": num_putaway, "num_stock_requests": num_stock_requests, "replenishment_items": replenishment_items}
    final_associates, unassigned_work = assign_and_balance_workload(associates_input, work_volumes, task_times, priorities, shift_minutes, target_efficiency)
    st.session_state.final_associates = final_associates
    st.session_state.unassigned_work = unassigned_work
    st.session_state.plan_generated = True

# --- Display Report ---
if st.session_state.plan_generated:
    st.header("Final Tasking Plan")
    report_cols = st.columns(len(st.session_state.final_associates)) if st.session_state.final_associates else []

    for i, assoc in enumerate(st.session_state.final_associates):
        with report_cols[i]:
            efficiency = calculate_efficiency(assoc["total_work"], shift_minutes)
            delta = efficiency - target_efficiency
            st.subheader(assoc['name'])
            st.metric(label="Efficiency vs. Target", value=f"{efficiency:.1f}%", delta=f"{delta:.1f}% vs {target_efficiency}%")
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
        if unassigned["fulfillment_minutes"] > 0:
            st.error("CRITICAL: Fulfillment work will be dropped due to over-assignment.")
            overloaded = [a for a in st.session_state.final_associates if a['fulfillment_overage'] > 0]
            for assoc in overloaded: st.write(f"  - **{assoc['name']}** is over capacity by **{assoc['fulfillment_overage']:.2f} minutes** from their fulfillment tasks alone.")
            underloaded = min((a for a in st.session_state.final_associates if not a['fulfillment_overage']), key=lambda x: x['total_work'], default=None)
            st.info("💡 **SUGGESTION:**")
            if underloaded: st.write(f"  Consider re-assigning a workcenter from **{overloaded[0]['name']}** to **{underloaded['name']}** and regenerate the plan.")
            else: st.write("  All associates are at/over capacity. Add more staff or reduce workload to meet targets.")
        
        if unassigned["putaway"] > 0 or unassigned["stock_request"] > 0:
            st.warning("The following secondary tasks will be carried over based on your priority ranking:")
            if unassigned["putaway"] > 0: st.write(f"- Unassigned Putaway Transactions: **{unassigned['putaway']}**")
            if unassigned["stock_request"] > 0: st.write(f"- Unassigned Stock Requests: **{unassigned['stock_request']}**")
    else:
        st.success("✅ All tasks have been successfully assigned within the target efficiency!")