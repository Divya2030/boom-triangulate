// Formal wrapper for the rename freelist.
//
// Holds no logic of its own: it instantiates the DUT and pulls in the same
// verif/checker.vh used by the simulation testbench, with FORMAL defined so the
// property wires become assumptions and assertions.
module freelist_fv (
    input wire       clk,
    input wire       reset,
    input wire       alloc_req,
    input wire       dealloc_valid,
    input wire [2:0] dealloc_preg,
    input wire       br_snapshot,
    input wire       br_rollback
);

  localparam NUM_PREGS = 8;
  localparam PREG_W    = 3;

  wire                 alloc_valid;
  wire [PREG_W-1:0]    alloc_preg;
  wire [NUM_PREGS-1:0] free_mask_o;
  wire [NUM_PREGS-1:0] snapshot_o;

  freelist #(.NUM_PREGS(NUM_PREGS), .PREG_W(PREG_W)) dut (
      .clk(clk), .reset(reset),
      .alloc_req(alloc_req), .alloc_valid(alloc_valid), .alloc_preg(alloc_preg),
      .dealloc_valid(dealloc_valid), .dealloc_preg(dealloc_preg),
      .br_snapshot(br_snapshot), .br_rollback(br_rollback),
      .free_mask_o(free_mask_o), .snapshot_o(snapshot_o));

`ifdef FORMAL
  // Constrain the initial state to a reset cycle, so traces start from the
  // architecturally defined state rather than an arbitrary one.
  reg f_init = 1'b1;
  always @(posedge clk) f_init <= 1'b0;
  always @(posedge clk) if (f_init) assume (reset);
`endif

  `include "checker.vh"

  // Reachability checks. These are the interesting ones: a cover that cannot be
  // reached means the assumptions have over-constrained the environment, which
  // is the failure mode the mutation campaign is also aimed at.
`ifdef FORMAL
  always @(posedge clk) begin
    if (!reset) begin
      cover (free_mask_o == NONE);                         // exhaust the free list
      cover (alloc_valid && (free_mask_o == ONE));         // allocate the last free preg
      cover (br_rollback && (shadow_alloc != shadow_snap));// rollback that undoes work
      cover (alloc_preg == (NUM_PREGS - 1));               // reach the top index
    end
  end
`endif

endmodule
