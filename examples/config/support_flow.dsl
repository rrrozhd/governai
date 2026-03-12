flow support_flow {
  entry: validate;
  policy: deny_send_without_approval;

  step validate: tool support.validate -> fetch_customer;
  step fetch_customer: tool customer.fetch -> draft_reply;
  step draft_reply: tool message.draft -> draft_shape;
  step draft_shape: tool draft.shape -> send_reply;
  step send_reply: tool message.send approval true -> end;
}
