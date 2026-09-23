// Cover-reachability wrapper.
//
// The yosys `sat` pass cannot evaluate $cover cells, so reachability is checked
// by refutation: assert the NEGATION of one cover condition and run BMC.
//
//   counterexample found -> the cover is REACHABLE   (good)
//   proof succeeds       -> the cover is UNREACHABLE (over-constrained, or dead
//                           logic -- either way a finding)
//
// checker.vh is included WITHOUT `FORMAL` so it contributes the shadow model and
// the assumption/property wires but none of its own assertions; the only assert
// in the design is the cover negation, so a counterexample is unambiguous.
//
// Select the cover point with one of -DCOVER_0 .. -DCOVER_3.
module freelist_cover (
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

  `include "checker.vh"

  reg f_init = 1'b1;
  always @(posedge clk) f_init <= 1'b0;

  // Same environment as the proof run: identical assumptions, identical reset.
  always @(posedge clk) begin
    if (f_init) assume (reset);
    if (!reset) begin
      assume (a1_dealloc_legal);
      assume (a2_rb_exclusive);
    end
  end

  wire cover_cond =
`ifdef COVER_0
      (free_mask_o == NONE);                          // exhaust the free list
`elsif COVER_1
      (alloc_valid && (free_mask_o == ONE));          // allocate the last free preg
`elsif COVER_2
      (br_rollback && (shadow_alloc != shadow_snap)); // rollback that undoes work
`elsif COVER_3
      (alloc_preg == (NUM_PREGS - 1));                // reach the top preg index
`else
      1'b0;
`endif

  always @(posedge clk) if (!reset) assert (!cover_cond);

endmodule
