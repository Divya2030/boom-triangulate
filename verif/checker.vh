// Shadow specification model + property set for the rename freelist.
//
// Included by BOTH verif/tb_freelist.v (simulation) and formal/freelist_fv.v
// (SymbiYosys), so there is exactly one copy of the spec. The includer must
// declare the DUT-facing nets by these names.
//
// Properties are exposed as plain wires so the simulation testbench can sample
// them and the formal wrapper can assert them, without duplicating the logic.

  localparam [NUM_PREGS-1:0] ALL_FREE = {NUM_PREGS{1'b1}};
  localparam [NUM_PREGS-1:0] NONE     = {NUM_PREGS{1'b0}};

  wire [NUM_PREGS-1:0] ONE = {{(NUM_PREGS-1){1'b0}}, 1'b1};

  // ---- shadow model: the set of pregs the spec believes are allocated ----
  reg [NUM_PREGS-1:0] shadow_alloc;
  reg [NUM_PREGS-1:0] shadow_snap;

  wire [NUM_PREGS-1:0] alloc_set_w   = alloc_valid   ? (ONE << alloc_preg)   : NONE;
  wire [NUM_PREGS-1:0] dealloc_set_w = dealloc_valid ? (ONE << dealloc_preg) : NONE;
  wire [NUM_PREGS-1:0] shadow_next   = (shadow_alloc | alloc_set_w) & ~dealloc_set_w;

  always @(posedge clk) begin
    if (reset) begin
      shadow_alloc <= NONE;
      shadow_snap  <= NONE;
    end else begin
      if (br_rollback) shadow_alloc <= shadow_snap;
      else             shadow_alloc <= shadow_next;
      if (br_snapshot) shadow_snap  <= shadow_next;
    end
  end

  // ---- history needed by the rollback property ----
  reg                 rb_prev;
  reg [NUM_PREGS-1:0] snap_prev;
  reg                 started;

  always @(posedge clk) begin
    rb_prev   <= reset ? 1'b0 : br_rollback;
    snap_prev <= snapshot_o;
    started   <= ~reset;
  end

  // ---- environment assumptions ----
  wire a1_dealloc_legal = (!dealloc_valid || !free_mask_o[dealloc_preg]);
  wire a2_rb_exclusive  = (!br_rollback   || (!alloc_req && !dealloc_valid));

  // ---- properties ----
  // P1: a preg is never simultaneously free and allocated.
  wire p1_mutex     = ((free_mask_o & shadow_alloc) == NONE);
  // P2: no leak -- every preg is either free or allocated.
  wire p2_complete  = ((free_mask_o | shadow_alloc) == ALL_FREE);
  // P3: an allocation only ever hands out a preg that was free.
  wire p3_no_dbl    = (!alloc_valid || free_mask_o[alloc_preg]);
  // P4: a rollback restores exactly the snapshotted mask.
  wire p4_rollback  = (!started || !rb_prev || (free_mask_o == snap_prev));
  // P5: allocation succeeds exactly when requested and a preg is available.
  wire p5_alloc_iff = (alloc_valid == (alloc_req && (free_mask_o != NONE)));

  // P6/P7: the snapshot pair must satisfy the same partition invariant as the
  // live pair, or a rollback installs an inconsistent state and breaks P1/P2.
  //
  // These are strengthening invariants, not independent claims: they were not
  // in the original property set and BMC never needed them. k-induction found
  // them, by starting from snapshot=0x71 / shadow_snap=0x0e -- a pair in which
  // preg 7 is neither snapshotted-free nor snapshotted-allocated. Such a state
  // is unreachable, but induction does not know that until it is asserted.
  wire p6_snap_mutex    = ((snapshot_o & shadow_snap) == NONE);
  wire p7_snap_complete = ((snapshot_o | shadow_snap) == ALL_FREE);

`ifdef FORMAL
  always @(posedge clk) begin
    if (!reset) begin
      assume (a1_dealloc_legal);
      assume (a2_rb_exclusive);

      assert (p1_mutex);
      assert (p2_complete);
      assert (p3_no_dbl);
      assert (p4_rollback);
      assert (p5_alloc_iff);
      assert (p6_snap_mutex);
      assert (p7_snap_complete);
    end
  end
`endif
